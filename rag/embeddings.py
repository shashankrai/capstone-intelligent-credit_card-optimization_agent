"""Local embeddings with a pluggable backend.

Two backends, both fully local (no API key):
- "fastembed": BAAI/bge-small-en-v1.5 (ONNX, 384-dim) — higher quality, downloads a model once.
- "hashing":   a dependency-free, no-download hashing embedding (384-dim) — works on locked-down
               networks that block model CDNs. Lower semantic quality, paired with the keyword
               boost in rag/retrieval.py.

EMBED_BACKEND ("auto" | "fastembed" | "hashing") in .env selects the backend; "auto" tries
fastembed and falls back to hashing if the model can't be loaded.
"""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from typing import List

import numpy as np

import config

_TOKEN = re.compile(r"[a-z0-9]+")


# --------------------------- hashing backend (no download) ---------------------------
def _tokens(text: str) -> List[str]:
    words = _TOKEN.findall(text.lower())
    bigrams = [f"{a}_{b}" for a, b in zip(words, words[1:])]
    return words + bigrams


def _hash_embed(text: str, dim: int = config.EMBED_DIM) -> List[float]:
    vec = np.zeros(dim, dtype="float32")
    for tok in _tokens(text):
        bucket = int(hashlib.md5(tok.encode()).hexdigest(), 16) % dim
        vec[bucket] += 1.0
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return vec.tolist()


# --------------------------- fastembed backend ---------------------------
@lru_cache(maxsize=1)
def _fastembed_model():
    from fastembed import TextEmbedding

    return TextEmbedding(model_name=config.EMBED_MODEL)


# --------------------------- backend selection ---------------------------
@lru_cache(maxsize=1)
def _backend() -> str:
    choice = config.EMBED_BACKEND
    if choice == "hashing":
        return "hashing"
    if choice == "fastembed":
        _fastembed_model()  # raises if unavailable
        return "fastembed"
    # auto
    try:
        _fastembed_model()
        return "fastembed"
    except Exception as exc:
        print(f"[embeddings] fastembed unavailable ({type(exc).__name__}); "
              f"using local hashing embeddings. Set EMBED_BACKEND=fastembed off a "
              f"restricted network for higher-quality vectors.")
        return "hashing"


def embed_texts(texts: List[str]) -> List[List[float]]:
    if _backend() == "fastembed":
        return [vec.tolist() for vec in _fastembed_model().embed(texts)]
    return [_hash_embed(t) for t in texts]


def embed_query(text: str) -> List[float]:
    if _backend() == "fastembed":
        prefixed = f"Represent this sentence for searching relevant passages: {text}"
        return next(iter(_fastembed_model().embed([prefixed]))).tolist()
    return _hash_embed(text)
