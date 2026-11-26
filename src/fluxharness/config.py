"""Provider selection. Speaks OpenAI-compatible chat/completions only."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Ordered by preference when several keys are present.
# (env key, base url, model env key, default model, display name)
_PROVIDERS = (
    ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1", "OPENROUTER_MODEL",
     "anthropic/claude-haiku-5.5", "openrouter"),
    ("GROQ_API_KEY", "https://api.groq.com/openai/v1", "GROQ_MODEL",
     "llama-3.3-70b-versatile", "groq"),
    ("OPENAI_API_KEY", "https://api.openai.com/v1", "OPENAI_MODEL",
     "gpt-4o-mini", "openai"),
    ("NVIDIA_API_KEY", "https://integrate.api.nvidia.com/v1", "NVIDIA_MODEL",
     "nvidia/nemotron-3.5-lightning-30b-a3b", "nvidia-nim"),
)


def _load_dotenv() -> None:
    """Pull KEY=VALUE pairs from .env into the environment, without overriding."""
    path = Path(__file__).resolve().parents[2] / ".env"
    if not path.is_file():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    base_url: str
    api_key: str
    model: str
    judge_model: str
    provider: str
    temperature: float = 0.2
    timeout: float = 120.0
    max_retries: int = 2
    # Reasoning models spend completion tokens thinking before they emit a
    # token of content. 4000 was not enough for a full spec + reasoning:
    # finish_reason "length", empty body, whole case lost.
    max_tokens: int = 8000

    @classmethod
    def detect(cls, temperature: float = 0.2) -> "Config":
        _load_dotenv()
        for key, base, model_key, default_model, display in _PROVIDERS:
            api_key = os.environ.get(key, "").strip()
            if api_key:
                return cls(
                    base_url=base,
                    api_key=api_key,
                    model=os.environ.get(model_key, "").strip() or default_model,
                    judge_model=os.environ.get("JUDGE_MODEL", "").strip(),
                    provider=display,
                    temperature=temperature,
                )
        raise ConfigError(
            "No API key found. Set OPENROUTER_API_KEY, GROQ_API_KEY, OPENAI_API_KEY "
            "or NVIDIA_API_KEY (env, or a .env next to AGENTS.md). See .env.example."
        )

    @property
    def effective_judge_model(self) -> str:
        return self.judge_model or self.model
