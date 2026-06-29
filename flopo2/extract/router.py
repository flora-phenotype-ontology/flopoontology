"""OpenRouter client with tiered model escalation (Phase 5).

Per the chosen design: a cheap open-weights workhorse handles the bulk, and segments that fail
(parse error, empty result, or explicit low-confidence) escalate to a more capable model. Reads
``OPENROUTER_API_KEY`` from the environment. JSON is requested via ``response_format`` and parsed
tolerantly (strips code fences, extracts the first JSON object) since open models vary in format
discipline.

Costs are tracked per call so the pilot can report actual spend. Nothing here is FLOPO-specific —
it is a thin, reusable LLM-call layer.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Approx OpenRouter prices ($/M tokens) for cost accounting (June 2026; see resources/openrouter-budget.md).
PRICES = {
    "openai/gpt-oss-120b": (0.03, 0.15),
    "openai/gpt-oss-20b": (0.03, 0.14),
    "qwen/qwen3-32b": (0.08, 0.28),
    "qwen/qwen3-235b-a22b": (0.195, 1.56),
    "mistralai/mistral-small": (0.15, 0.60),
    "deepseek/deepseek-v3.2": (0.23, 0.34),
    "z-ai/glm-4.6": (0.43, 1.74),
    "z-ai/glm-5.2": (0.95, 3.00),
}

_FENCE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)
_FIRST_OBJ = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class Usage:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    escalations: int = 0
    by_model: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, model: str, in_tok: int, out_tok: int) -> None:
        with self._lock:  # thread-safe: the pilot fans out API calls across worker threads
            self.calls += 1
            self.input_tokens += in_tok
            self.output_tokens += out_tok
            pin, pout = PRICES.get(model, (0.0, 0.0))
            self.cost_usd += in_tok / 1e6 * pin + out_tok / 1e6 * pout
            self.by_model[model] = self.by_model.get(model, 0) + 1


def parse_json(content: str) -> dict | None:
    """Tolerantly extract a JSON object from a model response."""
    if not content:
        return None
    txt = _FENCE.sub("", content).strip()
    try:
        return json.loads(txt)
    except json.JSONDecodeError:
        m = _FIRST_OBJ.search(txt)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                return None
    return None


class OpenRouterClient:
    def __init__(self, api_key: str | None = None, timeout: float = 120.0,
                 client: httpx.Client | None = None):
        self.api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
        self._client = client or httpx.Client(timeout=timeout)
        self.usage = Usage()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=30), reraise=True)
    def _post(self, payload: dict) -> dict:
        r = self._client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "HTTP-Referer": "https://github.com/flora-phenotype-ontology/flopoontology",
                "X-Title": "FLOPO 2.0",
            },
            json=payload,
        )
        r.raise_for_status()
        return r.json()

    def chat_json(self, model: str, system: str, user: str, temperature: float = 0.0) -> dict | None:
        """One chat completion expecting a JSON object; returns parsed dict (or None)."""
        payload = {
            "model": model,
            "temperature": temperature,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": user}],
            "response_format": {"type": "json_object"},
        }
        resp = self._post(payload)
        usage = resp.get("usage", {})
        self.usage.add(model, usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0))
        content = (resp.get("choices") or [{}])[0].get("message", {}).get("content", "")
        return parse_json(content)

    def chat_json_tiered(
        self, models: list[str], system: str, user: str, temperature: float = 0.0,
        ok=lambda d: bool(d and d.get("assertions") is not None),
    ) -> dict | None:
        """Try models in order; escalate to the next when the result fails ``ok``."""
        result = None
        for i, model in enumerate(models):
            try:
                result = self.chat_json(model, system, user, temperature)
            except Exception:
                result = None
            if ok(result):
                if i > 0:
                    self.usage.escalations += 1
                return result
        return result

    def close(self) -> None:
        self._client.close()
