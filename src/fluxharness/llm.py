"""Thin OpenAI-compatible chat client.

Deliberately not built on the `openai` package: one endpoint, one payload shape,
nothing to upgrade under us mid-recording. Retries are on transport and
malformed-JSON only. A valid "this is unanswerable" reply is not a failure.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import requests

from .config import Config

_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class LLMError(RuntimeError):
    pass


class RateLimited(LLMError):
    """429. Worth its own branch: the backoff that suits a 500 is useless here."""


class CompletionStarved(LLMError):
    """The model spent the whole token budget thinking and emitted nothing.

    Retrying with the same budget reproduces the same starvation, so the
    caller has to widen the budget instead of asking the same question again.
    """


class LLM:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.session = requests.Session()
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0

    def chat(
        self,
        system: str,
        user: str,
        *,
        json_mode: bool = True,
        temperature: float | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.cfg.temperature if temperature is None else temperature,
            # Reasoning models spend completion tokens on thinking before they
            # emit a token of content. Starve this and you get finish_reason
            # "length" with an empty body. A failure that looks like the
            # model ignored you.
            "max_tokens": self.cfg.max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        last: Exception | None = None
        for attempt in range(self.cfg.max_retries + 1):
            try:
                return self._post(payload, json_mode, attempt)
            except RateLimited as exc:
                last = exc
                if attempt < self.cfg.max_retries:
                    # Rate limits do not clear in 1.5s. Back off hard. A
                    # recording is the worst place to burn the remaining quota.
                    time.sleep(min(5 * (3 ** attempt), 30))
            except CompletionStarved as exc:
                last = exc
                if attempt < self.cfg.max_retries:
                    # The model thought until the budget ran out. Asking the
                    # same question with the same budget reproduces the same
                    # silence, so give it more room to finish thinking.
                    payload["max_tokens"] = min(payload["max_tokens"] * 2, 32768)
                    time.sleep(1.5 * (attempt + 1))
            except (requests.RequestException, LLMError) as exc:
                last = exc
                if attempt < self.cfg.max_retries:
                    time.sleep(1.5 * (attempt + 1))
        raise LLMError(f"LLM call failed after {self.cfg.max_retries + 1} attempts: {last}")

    def _post(self, payload: dict[str, Any], json_mode: bool, attempt: int) -> str:
        resp = self.session.post(
            f"{self.cfg.base_url.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.cfg.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.cfg.timeout,
        )
        # Some endpoints reject response_format; drop it and retry once.
        if resp.status_code == 400 and json_mode and "response_format" in payload:
            payload.pop("response_format", None)
            return self._post(payload, False, attempt)

        if resp.status_code == 429:
            raise RateLimited("rate limited")
        resp.raise_for_status()

        body = resp.json()
        self.calls += 1
        usage = body.get("usage") or {}
        self.tokens_in += usage.get("prompt_tokens", 0)
        self.tokens_out += usage.get("completion_tokens", 0)

        content = body["choices"][0]["message"].get("content") or ""
        if not content.strip():
            finish = body["choices"][0].get("finish_reason")
            if finish == "length":
                # Reasoning ate the budget; the answer never got written.
                raise CompletionStarved(
                    f"completion starved at max_tokens={payload.get('max_tokens')}"
                )
            raise LLMError(f"empty completion (finish_reason={finish!r})")
        return content

    def json(
        self,
        system: str,
        user: str,
        *,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Chat, then parse. One repair round if the model wrapped it in prose."""
        raw = self.chat(system, user, json_mode=True, temperature=temperature)
        try:
            return _parse(raw)
        except ValueError:
            repair = (
                "Your previous reply was not a single valid JSON object. "
                "Reply with the JSON object only. No markdown fence, no commentary.\n\n"
                f"Previous reply:\n{raw[:2000]}"
            )
            raw = self.chat(system, repair, json_mode=False, temperature=0)
            return _parse(raw)


def _parse(raw: str) -> dict[str, Any]:
    text = raw.strip()
    fenced = _FENCE.search(text)
    if fenced:
        text = fenced.group(1).strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("no JSON object found")
        text = text[start : end + 1]
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("top level is not an object")
    return value
