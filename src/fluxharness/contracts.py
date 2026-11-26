"""Typed handoff contracts between sub-agents.

A stage emits one of these; the next stage only ever receives a validated one.
If a model returns something malformed, the failure names the stage and the
field rather than surfacing three stages downstream as a confusing eval failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class ContractError(ValueError):
    """A stage produced something that is not a valid record."""

    def __init__(self, stage: str, problems: list[str]):
        self.stage = stage
        self.problems = problems
        super().__init__(f"[{stage}] " + "; ".join(problems))


def _strings(stage: str, obj: dict, key: str, *, min_len: int = 1, max_len: int = 40) -> list[str]:
    if key not in obj:
        raise ContractError(stage, [f"missing field '{key}'"])
    value = obj[key]
    if not isinstance(value, list):
        raise ContractError(stage, [f"'{key}' must be a list, got {type(value).__name__}"])
    problems: list[str] = []
    out: list[str] = []
    for i, item in enumerate(value):
        if not isinstance(item, str):
            problems.append(f"'{key}[{i}]' is not a string")
            continue
        item = item.strip()
        if not item:
            problems.append(f"'{key}[{i}]' is empty")
            continue
        # Cap a runaway item rather than failing: bounding is cheap, and the
        # alternative punishes a model for being thorough.
        out.append(item[:400])
    if len(out) < min_len:
        problems.append(f"'{key}' needs at least {min_len} item(s), got {len(out)}")
    if problems:
        raise ContractError(stage, problems)
    # Too many is a size problem; too few is a did-not-do-the-job problem.
    # We cap the first and fail the second.
    return out[:max_len]


def _text(stage: str, obj: dict, key: str, *, lo: int = 1, hi: int = 600) -> str:
    if key not in obj:
        raise ContractError(stage, [f"missing field '{key}'"])
    value = obj[key]
    if not isinstance(value, str) or not value.strip():
        raise ContractError(stage, [f"'{key}' must be a non-empty string"])
    value = value.strip()
    if not lo <= len(value) <= hi:
        raise ContractError(stage, [f"'{key}' is {len(value)} chars, outside {lo}-{hi}"])
    return value


# --------------------------------------------------------------------------
# Stage 1 -- Scout
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Brief:
    idea: str
    users: list[str]
    core_jobs: list[str]
    constraints: list[str]
    ambiguities: list[str]
    success_criteria: list[str]

    @classmethod
    def from_dict(cls, stage: str, obj: dict) -> "Brief":
        if not isinstance(obj, dict):
            raise ContractError(stage, ["top level is not an object"])
        return cls(
            idea=_text(stage, obj, "idea", lo=3, hi=300),
            users=_strings(stage, obj, "users", min_len=1, max_len=6),
            core_jobs=_strings(stage, obj, "core_jobs", min_len=2, max_len=8),
            constraints=_strings(stage, obj, "constraints", min_len=1, max_len=8),
            ambiguities=_strings(stage, obj, "ambiguities", min_len=1, max_len=8),
            success_criteria=_strings(stage, obj, "success_criteria", min_len=2, max_len=6),
        )

    def to_dict(self) -> dict:
        return {
            "idea": self.idea,
            "users": self.users,
            "core_jobs": self.core_jobs,
            "constraints": self.constraints,
            "ambiguities": self.ambiguities,
            "success_criteria": self.success_criteria,
        }


# --------------------------------------------------------------------------
# Stage 2 -- Architect
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Entity:
    name: str
    fields: list[str]


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    purpose: str


@dataclass(frozen=True)
class Spec:
    name: str
    one_liner: str
    stack: list[str]
    entities: list[Entity]
    endpoints: list[Endpoint]
    screens: list[str]
    out_of_scope: list[str]
    milestones: list[str]

    @classmethod
    def from_dict(cls, stage: str, obj: dict) -> "Spec":
        if not isinstance(obj, dict):
            raise ContractError(stage, ["top level is not an object"])
        # Report absent keys before counting anything: "you forgot 'stack'" is
        # more actionable than "you have 0 entities".
        required = ("name", "one_liner", "stack", "entities", "endpoints",
                    "screens", "out_of_scope", "milestones")
        missing = [k for k in required if k not in obj]
        if missing:
            raise ContractError(stage, [f"missing field '{k}'" for k in missing])

        problems: list[str] = []

        entities: list[Entity] = []
        for i, raw in enumerate(obj.get("entities") or []):
            if not isinstance(raw, dict) or not isinstance(raw.get("name"), str):
                problems.append(f"entities[{i}] must be an object with a 'name'")
                continue
            fields = raw.get("fields")
            if not isinstance(fields, list) or not all(isinstance(f, str) and f.strip() for f in fields):
                problems.append(f"entities[{i}].fields must be a list of non-empty strings")
                continue
            entities.append(Entity(raw["name"].strip(), [f.strip() for f in fields]))
        if len(entities) < 2:
            problems.append(f"entities needs at least 2, got {len(entities)}")
        elif len(entities) > 15:
            entities = entities[:15]  # cap, do not fail

        endpoints: list[Endpoint] = []
        allowed = {"GET", "POST", "PUT", "PATCH", "DELETE"}
        for i, raw in enumerate(obj.get("endpoints") or []):
            if not isinstance(raw, dict):
                problems.append(f"endpoints[{i}] must be an object")
                continue
            method = str(raw.get("method", "")).upper().strip()
            path, purpose = raw.get("path"), raw.get("purpose")
            if method not in allowed:
                problems.append(f"endpoints[{i}].method '{method}' is not a valid HTTP verb")
                continue
            if not isinstance(path, str) or not path.startswith("/"):
                problems.append(f"endpoints[{i}].path must start with '/'")
                continue
            if not isinstance(purpose, str) or not purpose.strip():
                problems.append(f"endpoints[{i}].purpose is missing")
                continue
            endpoints.append(Endpoint(method, path.strip(), purpose.strip()))
        if len(endpoints) < 3:
            problems.append(f"endpoints needs at least 3, got {len(endpoints)}")
        elif len(endpoints) > 25:
            endpoints = endpoints[:25]  # cap, do not fail

        if problems:
            raise ContractError(stage, problems)

        return cls(
            name=_text(stage, obj, "name", lo=2, hi=60),
            one_liner=_text(stage, obj, "one_liner", lo=10, hi=300),
            stack=_strings(stage, obj, "stack", min_len=2, max_len=12),
            entities=entities,
            endpoints=endpoints,
            screens=_strings(stage, obj, "screens", min_len=1, max_len=10),
            out_of_scope=_strings(stage, obj, "out_of_scope", min_len=1, max_len=8),
            milestones=_strings(stage, obj, "milestones", min_len=3, max_len=8),
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "one_liner": self.one_liner,
            "stack": self.stack,
            "entities": [{"name": e.name, "fields": e.fields} for e in self.entities],
            "endpoints": [{"method": e.method, "path": e.path, "purpose": e.purpose} for e in self.endpoints],
            "screens": self.screens,
            "out_of_scope": self.out_of_scope,
            "milestones": self.milestones,
        }


# --------------------------------------------------------------------------
# Stage 3 -- Critic
# --------------------------------------------------------------------------
VERDICTS = ("ship", "revise", "blocked")


@dataclass(frozen=True)
class Review:
    verdict: str
    gaps: list[str]
    risks: list[str]
    confidence: float
    spec: Spec

    @classmethod
    def from_dict(cls, stage: str, obj: dict) -> "Review":
        if not isinstance(obj, dict):
            raise ContractError(stage, ["top level is not an object"])
        verdict = obj.get("verdict")
        if verdict not in VERDICTS:
            raise ContractError(stage, [f"verdict must be one of {VERDICTS}, got {verdict!r}"])

        confidence = obj.get("confidence")
        if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            raise ContractError(stage, ["confidence must be a number in [0, 1]"])

        if "spec" not in obj:
            raise ContractError(stage, ["missing field 'spec' (the revised spec must be returned)"])

        return cls(
            verdict=verdict,
            gaps=_strings(stage, obj, "gaps", min_len=1, max_len=8),
            risks=_strings(stage, obj, "risks", min_len=1, max_len=8),
            confidence=float(confidence),
            spec=Spec.from_dict(stage, obj["spec"]),
        )

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "gaps": self.gaps,
            "risks": self.risks,
            "confidence": self.confidence,
            "spec": self.spec.to_dict(),
        }
