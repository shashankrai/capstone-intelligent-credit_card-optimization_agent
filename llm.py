"""Provider-agnostic LLM wrapper (via LiteLLM).

One place for all LLM calls. The active model is `config.LLM_MODEL` ("<provider>/<model>"),
so the whole app works with Anthropic, OpenAI, Gemini, or local Ollama by changing one env var.
Public interface is unchanged: complete(), complete_json(), web_search_complete().
"""
from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Dict, Tuple

import litellm

import config

litellm.drop_params = True  # silently drop params a given provider doesn't support


def _base_kwargs(max_tokens: int) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {
        "model": config.LLM_MODEL,
        "max_tokens": max_tokens,
        "timeout": config.LLM_TIMEOUT,       # bounded so a slow provider fails instead of hanging
        "num_retries": config.LLM_NUM_RETRIES,
    }
    if config.LLM_PROVIDER == "ollama":
        kwargs["api_base"] = config.OLLAMA_API_BASE
    return kwargs


def _usage(resp) -> Dict[str, int]:
    u = getattr(resp, "usage", None)
    if not u:
        return {"input_tokens": 0, "output_tokens": 0}
    return {
        "input_tokens": getattr(u, "prompt_tokens", 0) or 0,
        "output_tokens": getattr(u, "completion_tokens", 0) or 0,
    }


def _content(resp) -> str:
    try:
        return (resp.choices[0].message.content or "").strip()
    except (AttributeError, IndexError):
        return ""


def complete(system: str, user: str, max_tokens: int = 4096,
             thinking: bool = False) -> Tuple[str, Dict[str, int]]:
    """Plain text completion. Returns (text, usage)."""
    kwargs = _base_kwargs(max_tokens)
    kwargs["messages"] = [{"role": "system", "content": system},
                          {"role": "user", "content": user}]
    # Extended thinking is Anthropic-specific; enable only when asked and on Anthropic.
    if thinking and config.CLAUDE_THINKING and config.LLM_PROVIDER == "anthropic" and max_tokens > 1536:
        kwargs["thinking"] = {"type": "enabled", "budget_tokens": 1024}
    resp = litellm.completion(**kwargs)
    return (_content(resp), _usage(resp))


def _parse_json(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        cleaned = text.strip().strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
        # last resort: slice the outermost object
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end != -1:
            cleaned = cleaned[start:end + 1]
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {}


def complete_json(system: str, user: str, schema: Dict[str, Any],
                  max_tokens: int = 2048) -> Tuple[Dict[str, Any], Dict[str, int]]:
    """Schema-constrained JSON output (LiteLLM translates per provider). Returns (dict, usage)."""
    kwargs = _base_kwargs(max_tokens)
    kwargs["messages"] = [{"role": "system", "content": system},
                          {"role": "user", "content": user}]
    kwargs["response_format"] = {
        "type": "json_schema",
        "json_schema": {"name": "structured_output", "schema": schema, "strict": True},
    }
    try:
        resp = litellm.completion(**kwargs)
        parsed = _parse_json(_content(resp))
        if parsed:
            return (parsed, _usage(resp))
    except Exception as exc:  # provider rejected response_format, etc. — fall back below
        print(f"[llm] structured call fell back to prompt-JSON: {type(exc).__name__}")

    # Fallback: ask for JSON in the prompt and parse.
    instr = (f"{system}\n\nRespond with ONLY a JSON object matching this schema "
             f"(no prose, no code fences):\n{json.dumps(schema)}")
    text, usage = complete(instr, user, max_tokens=max_tokens)
    return (_parse_json(text), usage)


# --------------------------------------------------------------------------- #
# Web search — used by the "add card by name" flow. Provider-specific.
# --------------------------------------------------------------------------- #
@lru_cache(maxsize=1)
def _anthropic_client():
    import anthropic

    return anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)


def web_search_complete(system: str, user: str, max_tokens: int = 4096,
                        max_uses: int = 6) -> Tuple[str, Dict[str, int]]:
    """Text completion with live web search. Currently implemented for Anthropic (native tool).

    For other providers, raises with guidance to use rag/collect_web.py or switch to Anthropic.
    """
    if config.LLM_PROVIDER != "anthropic":
        raise RuntimeError(
            f"Web-search add-a-card needs the Anthropic provider (current: {config.LLM_PROVIDER}). "
            f"Set LLM_MODEL=anthropic/claude-... , or use rag/collect_web.py with curated URLs, "
            f"or add the card via PDF upload."
        )
    import anthropic

    try:
        resp = _anthropic_client().messages.create(
            model=config.CLAUDE_MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses}],
        )
    except anthropic.BadRequestError as exc:
        raise RuntimeError(
            "Web search is not enabled on this Anthropic account/model. Enable it in the Anthropic "
            "Console, or use rag/collect_web.py with curated URLs instead."
        ) from exc
    text = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
    u = getattr(resp, "usage", None)
    usage = {"input_tokens": getattr(u, "input_tokens", 0) or 0,
             "output_tokens": getattr(u, "output_tokens", 0) or 0}
    return (text.strip(), usage)
