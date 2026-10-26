"""Meta Model API client with caching, token logging, and a rule-based fallback.

Modes
-----
* ``api`` — META_MODEL_API_KEY is set. Talks to the Meta Model API, which is
  OpenAI-compatible (base URL ``https://api.meta.ai/v1``, POST
  ``/chat/completions``, Bearer key). Verified against public docs
  (dev.meta.ai/docs) as of 2026-10-13; re-verify at hackathon kickoff.
* ``fallback`` — no key. A deterministic investigator is *not* possible here
  (this module is transport-only); the agent in ``agent.py`` switches to its
  rule-based investigator and every result is tagged
  ``mode="fallback"`` so API vs fallback runs are never confused.

Model routing
-------------
``META_MODEL_SMALL`` (default ``muse-spark-1.3``) for routine steps,
``META_MODEL_LARGE`` (default ``muse-spark-1.3`` until the hackathon model
list is confirmed) for hard investigations — vision reads and low-confidence
cases. Override via env without code changes.

Budget
------
Responses are cached on disk (``data/llm_cache``) keyed by request hash.
Every call — cached or not — appends to ``data/token_usage.jsonl`` with
model, token counts and estimated USD (muse-spark-1.3 Standard pricing:
$1.25/1M input, $4.25/1M output tokens; override with
META_PRICE_INPUT_1M / META_PRICE_OUTPUT_1M).
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_BASE = "https://api.meta.ai/v1"
DEFAULT_SMALL = "muse-spark-1.3"


def extract_json_object(text: str | None) -> dict | None:
    """Parse a model reply as a JSON object, tolerating prose around it.

    The live model often answers with prose before or around the JSON
    (verified 2026-10-26: a bare prose reply, then a prose prefix ahead of
    a valid tool_call). A strict ``json.loads`` discards the whole reply
    in both cases. This tries the full text first, then the substring
    from the first ``{`` to the last ``}``. Returns None when neither
    parses (including a None/empty reply, which happens when reasoning
    tokens consume a small max_tokens budget).
    """
    if not text:
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
DEFAULT_LARGE = "muse-spark-1.3"  # finalized at kickoff; see DECISIONS.md


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


class LLMClient:
    def __init__(self, data_dir: Path | None = None):
        self.root = _project_root()
        self.data_dir = Path(data_dir) if data_dir else self.root / "data"
        self.cache_dir = self.data_dir / "llm_cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.usage_log = self.data_dir / "token_usage.jsonl"

        self.api_key = os.environ.get("META_MODEL_API_KEY", "").strip()
        self.base_url = os.environ.get("META_MODEL_API_BASE", DEFAULT_BASE).rstrip("/")
        self.small_model = os.environ.get("META_MODEL_SMALL", DEFAULT_SMALL)
        self.large_model = os.environ.get("META_MODEL_LARGE", DEFAULT_LARGE)
        self.price_in = float(os.environ.get("META_PRICE_INPUT_1M", "1.25"))
        self.price_out = float(os.environ.get("META_PRICE_OUTPUT_1M", "4.25"))

        self.mode = "api" if self.api_key else "fallback"

    # -- public ------------------------------------------------------------- #
    def model_for(self, hard: bool = False) -> str:
        return self.large_model if hard else self.small_model

    def chat(self, messages: list[dict], hard: bool = False,
             purpose: str = "investigate", use_cache: bool = True,
             temperature: float = 0.2, max_tokens: int = 1500) -> dict:
        """Returns {text, model, usage{...}, cached, mode}. Raises in api mode
        only if the HTTP call itself fails (caller may then fall back)."""
        if self.mode == "fallback":
            raise RuntimeError("LLMClient.chat called in fallback mode")
        model = self.model_for(hard)
        key = self._cache_key(model, messages)
        if use_cache:
            hit = self._cache_read(key)
            if hit is not None:
                self._log_usage(model, 0, 0, cached=True, purpose=purpose)
                return {**hit, "cached": True, "mode": "api"}

        body = {"model": model, "messages": messages,
                "temperature": temperature, "max_tokens": max_tokens,
                "response_format": {"type": "json_object"}}
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {self.api_key}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                payload = json.loads(resp.read().decode())
        except Exception as e:
            raise RuntimeError(f"Meta Model API call failed: {e}") from e

        text = payload["choices"][0]["message"]["content"]
        usage = payload.get("usage", {})
        result = {"text": text, "model": model,
                  "usage": {"prompt_tokens": usage.get("prompt_tokens", 0),
                            "completion_tokens": usage.get("completion_tokens", 0)},
                  "cached": False, "mode": "api"}
        self._cache_write(key, {k: v for k, v in result.items() if k != "cached"})
        self._log_usage(model, result["usage"]["prompt_tokens"],
                        result["usage"]["completion_tokens"],
                        cached=False, purpose=purpose)
        return result

    def log_fallback_call(self, purpose: str = "investigate") -> None:
        self._log_usage("rule-based-fallback", 0, 0, cached=False,
                        purpose=purpose, mode="fallback")

    @staticmethod
    def image_message(prompt: str, image_path: Path) -> dict:
        b64 = base64.b64encode(Path(image_path).read_bytes()).decode()
        return {"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url",
             "image_url": {"url": f"data:image/png;base64,{b64}"}}]}

    # -- internals ---------------------------------------------------------- #
    @staticmethod
    def _cache_key(model: str, messages: list[dict]) -> str:
        blob = json.dumps({"model": model, "messages": messages},
                          sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()

    def _cache_read(self, key: str) -> dict | None:
        p = self.cache_dir / f"{key}.json"
        if p.exists():
            return json.loads(p.read_text())
        return None

    def _cache_write(self, key: str, result: dict) -> None:
        (self.cache_dir / f"{key}.json").write_text(json.dumps(result))

    def _log_usage(self, model: str, prompt_tokens: int, completion_tokens: int,
                   cached: bool, purpose: str, mode: str | None = None) -> None:
        cost = (prompt_tokens / 1e6) * self.price_in + \
               (completion_tokens / 1e6) * self.price_out
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "mode": mode or self.mode,
            "model": model,
            "purpose": purpose,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "cached": cached,
            "est_cost_usd": round(cost, 6),
        }
        with open(self.usage_log, "a") as f:
            f.write(json.dumps(entry) + "\n")
