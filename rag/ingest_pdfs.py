"""Layer 1 — Data ingestion (generic, manifest-driven).

Reads card documents (.pdf / .md / .txt) from data/cards, extracts text page-by-page,
splits into chunks, generates embeddings, and stores them in PostgreSQL
(card_documents + document_chunks).

Document metadata (card_name, issuer, effective_date, source_url) is taken from
data/cards/manifest.csv when present; any files not listed there are still ingested
with metadata derived from the filename. This lets you drop in real official bank PDFs
without touching code.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import config
from database.db import get_conn
from rag.embeddings import embed_texts

MANIFEST = config.CARDS_DIR / "manifest.csv"


# --------------------------------------------------------------------------- #
# text extraction (page-aware)
# --------------------------------------------------------------------------- #
def extract_pages(path: Path) -> List[Tuple[int, str]]:
    """Return [(page_number, text), ...]. Non-PDF files are treated as a single page."""
    if path.suffix.lower() == ".pdf":
        import fitz  # pymupdf

        doc = fitz.open(path)
        pages = [(i + 1, page.get_text()) for i, page in enumerate(doc)]
        doc.close()
        return [(n, t) for n, t in pages if t and t.strip()]
    return [(1, path.read_text(encoding="utf-8"))]


def chunk_text(text: str, size: int = config.CHUNK_SIZE, overlap: int = config.CHUNK_OVERLAP) -> List[str]:
    """Pack paragraph/heading blocks into ~`size`-char chunks with overlap."""
    paragraphs = re.split(r"\n\s*\n", text.strip())
    chunks: List[str] = []
    buf = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(buf) + len(para) + 2 <= size:
            buf = f"{buf}\n\n{para}" if buf else para
        else:
            if buf:
                chunks.append(buf)
            if len(para) > size:
                for i in range(0, len(para), size - overlap):
                    chunks.append(para[i : i + size])
                buf = ""
            else:
                buf = para
    if buf:
        chunks.append(buf)
    return chunks


# --------------------------------------------------------------------------- #
# manifest + file discovery
# --------------------------------------------------------------------------- #
class DocSpec:
    def __init__(self, path: Path, card_name: str, issuer: Optional[str],
                 doc_type: str, effective_date: Optional[str], source_url: Optional[str]):
        self.path = path
        self.card_name = card_name
        self.issuer = issuer
        self.doc_type = doc_type
        self.effective_date = effective_date or None
        self.source_url = source_url


def _load_manifest() -> Dict[str, Dict[str, str]]:
    """Manifest keyed by file stem (extension-independent), so one row covers .md or .pdf."""
    if not MANIFEST.exists():
        return {}
    with MANIFEST.open() as f:
        return {row["stem"]: row for row in csv.DictReader(f)}


def _derive_name(path: Path) -> str:
    return path.stem.replace("_", " ").replace("-", " ").title()


# When both a real PDF and the illustrative .md exist for the same card, prefer the PDF.
_EXT_PRIORITY = {".pdf": 0, ".txt": 1, ".md": 2}


def discover_docs() -> List[DocSpec]:
    """One DocSpec per card (by stem), preferring PDF over md/txt, enriched by manifest metadata."""
    manifest = _load_manifest()

    best_by_stem: Dict[str, Path] = {}
    for ext in ("*.pdf", "*.md", "*.txt"):
        for path in config.CARDS_DIR.glob(ext):
            cur = best_by_stem.get(path.stem)
            if cur is None or _EXT_PRIORITY[path.suffix.lower()] < _EXT_PRIORITY[cur.suffix.lower()]:
                best_by_stem[path.stem] = path

    specs: List[DocSpec] = []
    for stem, path in sorted(best_by_stem.items()):
        row = manifest.get(stem)
        if row:
            specs.append(DocSpec(path, row.get("card_name") or _derive_name(path),
                                 row.get("issuer"), row.get("document_type") or "terms_and_rewards",
                                 row.get("effective_date"), row.get("source_url")))
        else:
            specs.append(DocSpec(path, _derive_name(path), None, "terms_and_rewards", None, str(path)))
    return specs


# --------------------------------------------------------------------------- #
# ingestion
# --------------------------------------------------------------------------- #
def _rebuild_vector_index(cur) -> None:
    cur.execute("DROP INDEX IF EXISTS document_chunks_embedding_idx;")
    cur.execute(
        "CREATE INDEX document_chunks_embedding_idx ON document_chunks "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);"
    )


def ingest_one(spec: DocSpec, reset_card: bool = True) -> Tuple[int, int]:
    """Ingest a single document. If reset_card, first remove any existing doc for that card_name.

    Shared by ingest_all() and the 'add a card' flows (web/PDF). Returns (document_id, n_chunks).
    """
    with get_conn() as conn, conn.cursor() as cur:
        if reset_card:
            cur.execute("DELETE FROM card_documents WHERE card_name = %s;", (spec.card_name,))

        cur.execute(
            """INSERT INTO card_documents (card_name, issuer, document_type, effective_date, source_url)
               VALUES (%s, %s, %s, %s, %s) RETURNING document_id;""",
            (spec.card_name, spec.issuer, spec.doc_type, spec.effective_date, spec.source_url),
        )
        document_id = cur.fetchone()["document_id"]

        doc_chunks: List[Tuple[str, int]] = []
        for page_no, page_text in extract_pages(spec.path):
            for chunk in chunk_text(page_text):
                doc_chunks.append((chunk, page_no))
        if not doc_chunks:
            raise ValueError(f"No extractable text in {spec.path.name} (scanned PDF?).")

        embeddings = embed_texts([c for c, _ in doc_chunks])
        for (chunk, page_no), emb in zip(doc_chunks, embeddings):
            cur.execute(
                """INSERT INTO document_chunks
                   (document_id, card_name, chunk_text, page_number, embedding, metadata_json)
                   VALUES (%s, %s, %s, %s, %s, %s);""",
                (document_id, spec.card_name, chunk, page_no, emb, '{"source": "%s"}' % spec.path.name),
            )
        _rebuild_vector_index(cur)
    return document_id, len(doc_chunks)


def ingest_all(reset: bool = True) -> Tuple[int, int]:
    """Ingest every discovered document. Returns (#documents, #chunks)."""
    specs = discover_docs()
    if not specs:
        raise FileNotFoundError(
            f"No card documents found in {config.CARDS_DIR}. Add PDFs (see manifest.csv) "
            "or the illustrative .md files."
        )

    total_docs = total_chunks = 0
    with get_conn() as conn, conn.cursor() as cur:
        if reset:
            cur.execute("TRUNCATE document_chunks, card_documents RESTART IDENTITY CASCADE;")

        for spec in specs:
            cur.execute(
                """INSERT INTO card_documents (card_name, issuer, document_type, effective_date, source_url)
                   VALUES (%s, %s, %s, %s, %s) RETURNING document_id;""",
                (spec.card_name, spec.issuer, spec.doc_type, spec.effective_date, spec.source_url),
            )
            document_id = cur.fetchone()["document_id"]
            total_docs += 1

            doc_chunks: List[Tuple[str, int]] = []
            for page_no, page_text in extract_pages(spec.path):
                for chunk in chunk_text(page_text):
                    doc_chunks.append((chunk, page_no))

            if not doc_chunks:
                print(f"  WARNING {spec.card_name} ({spec.path.name}): no extractable text (scanned PDF?)")
                continue

            embeddings = embed_texts([c for c, _ in doc_chunks])
            for (chunk, page_no), emb in zip(doc_chunks, embeddings):
                cur.execute(
                    """INSERT INTO document_chunks
                       (document_id, card_name, chunk_text, page_number, embedding, metadata_json)
                       VALUES (%s, %s, %s, %s, %s, %s);""",
                    (document_id, spec.card_name, chunk, page_no, emb,
                     '{"source": "%s"}' % spec.path.name),
                )
            total_chunks += len(doc_chunks)
            print(f"  ingested {spec.card_name} ({spec.path.name}): {len(doc_chunks)} chunks")

        cur.execute("DROP INDEX IF EXISTS document_chunks_embedding_idx;")
        cur.execute(
            "CREATE INDEX document_chunks_embedding_idx ON document_chunks "
            "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 10);"
        )
    return total_docs, total_chunks


if __name__ == "__main__":
    docs, chunks = ingest_all()
    print(f"Ingested {docs} documents, {chunks} chunks.")
