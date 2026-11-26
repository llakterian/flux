"""Typed handoff records between sub-agents.

A sub-agent that produces garbage must fail *at its own stage*, named — not
three stages downstream when someone finally reads the garbage in an eval.
These records are the contract: validated on the way out of one stage and on
the way into the next, with errors that name the stage and the offending field.

Tradeoff: a little ceremony per field, in exchange for failures you can read
like a sentence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar


class ContractError(Exception):
    """Validation failure on a stage handoff.

    The message always names the stage and the offending field(s):
    `[architect] entities needs at least 2, got 1`.
    """

    def __init__(self, stage: str, problems: list[str]):
        self.stage = stage
        self.problems = list(problems)
        super().__init__(f"[{stage}] " + "; ".join(self.problems))


def _str_list(obj: dict, key: str, problems: list[str]) -> list[str]:
    """Pull a list-of-strings field, reporting type problems."""
    value = obj.get(key)
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        problems.append(f"{key} must be an array of strings")
        return []
    return value


def _bounded(
    key: str, items: list, low: int, high: int, problems: list[str]
) -> list:
    """Overflow caps; shortfall fails.

    Too many items is a size problem — keep the first `high` and move on.
    Too few is a did-not-do-the-job problem — fail the stage.
    """
    if len(items) < low:
        problems.append(f"{key} needs at least {low}, got {len(items)}")
        return items
    return items[:high]


def _check_len(key: str, value: str, low: int, high: int, problems: list[str]) -> None:
    if not isinstance(value, str):
        problems.append(f"{key} must be a string")
    elif len(value) < low:
        problems.append(f"{key} must be at least {low} chars, got {len(value)}")
    elif len(value) > high:
        problems.append(f"{key} must be at most {high} chars, got {len(value)}")


@dataclass(frozen=True)
class Entity:
    name: str
    fields: list[str]

    def to_dict(self) -> dict:
        return {"name": self.name, "fields": list(self.fields)}

    @classmethod
    def from_dict(cls, obj: Any, problems: list[str], where: str) -> "Entity | None":
        if not isinstance(obj, dict):
            problems.append(f"{where} must be an object with name/fields")
            return None
        name, fields_ = obj.get("name"), obj.get("fields")
        if not isinstance(name, str) or not name:
            problems.append(f"{where}.name must be a non-empty string")
        if not isinstance(fields_, list) or not all(
            isinstance(v, str) for v in fields_
        ):
            problems.append(f"{where}.fields must be an array of strings")
        if name and isinstance(fields_, list):
            return cls(name=name, fields=fields_)
        return None


@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    purpose: str

    def to_dict(self) -> dict:
        return {"method": self.method, "path": self.path, "purpose": self.purpose}

    @classmethod
    def from_dict(cls, obj: Any, problems: list[str], where: str) -> "Endpoint | None":
        if not isinstance(obj, dict):
            problems.append(f"{where} must be an object with method/path/purpose")
            return None
        method, path = obj.get("method"), obj.get("path")
        purpose = obj.get("purpose", "")
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            problems.append(
                f"{where}.method must be one of GET/POST/PUT/PATCH/DELETE, got {method!r}"
            )
        if not isinstance(path, str) or not path.startswith("/"):
            problems.append(f"{where}.path must start with '/', got {path!r}")
        if method in ("GET", "POST", "PUT", "PATCH", "DELETE") and isinstance(
            path, str
        ) and path.startswith("/"):
            return cls(method=method, path=path, purpose=str(purpose))
        return None


@dataclass(frozen=True)
class Brief:
    """Scout's output: the idea, pinned down."""

    ENTITY_MIN: ClassVar[int] = 0  # not used on Brief; keeps linters quiet

    idea: str
    users: list[str]
    core_jobs: list[str]
    constraints: list[str]
    ambiguities: list[str]
    success_criteria: list[str]

    _REQUIRED: ClassVar[tuple] = (
        "idea", "users", "core_jobs", "constraints", "ambiguities", "success_criteria",
    )

    @classmethod
    def from_dict(cls, stage: str, obj: Any) -> "Brief":
        problems: list[str] = []
        if not isinstance(obj, dict):
            raise ContractError(stage, ["expected a JSON object"])
        # Report missing keys before counting anything else.
        missing = [k for k in cls._REQUIRED if k not in obj]
        if missing:
            raise ContractError(stage, [f"missing field '{m}'" for m in missing])

        idea = obj.get("idea")
        _check_len("idea", idea if isinstance(idea, str) else "", 3, 300, problems)
        users = _bounded("users", _str_list(obj, "users", problems), 1, 6, problems)
        core_jobs = _bounded("core_jobs", _str_list(obj, "core_jobs", problems), 2, 8, problems)
        constraints = _bounded("constraints", _str_list(obj, "constraints", problems), 1, 8, problems)
        ambiguities = _bounded("ambiguities", _str_list(obj, "ambiguities", problems), 1, 8, problems)
        success = _bounded("success_criteria", _str_list(obj, "success_criteria", problems), 2, 6, problems)

        if problems:
            raise ContractError(stage, problems)
        return cls(
            idea=idea, users=users, core_jobs=core_jobs, constraints=constraints,
            ambiguities=ambiguities, success_criteria=success,
        )

    def to_dict(self) -> dict:
        return {
            "idea": self.idea, "users": list(self.users),
            "core_jobs": list(self.core_jobs), "constraints": list(self.constraints),
            "ambiguities": list(self.ambiguities),
            "success_criteria": list(self.success_criteria),
        }


@dataclass(frozen=True)
class Spec:
    """Architect's output: the buildable spec."""

    name: str
    one_liner: str
    stack: list[str]
    entities: list[Entity]
    endpoints: list[Endpoint]
    screens: list[str]
    out_of_scope: list[str]
    milestones: list[str]

    _REQUIRED: ClassVar[tuple] = (
        "name", "one_liner", "stack", "entities", "endpoints", "screens",
        "out_of_scope", "milestones",
    )

    @classmethod
    def from_dict(cls, stage: str, obj: Any) -> "Spec":
        problems: list[str] = []
        if not isinstance(obj, dict):
            raise ContractError(stage, ["expected a JSON object"])
        missing = [k for k in cls._REQUIRED if k not in obj]
        if missing:
            raise ContractError(stage, [f"missing field '{m}'" for m in missing])

        _check_len("name", obj.get("name") if isinstance(obj.get("name"), str) else "", 2, 60, problems)
        _check_len("one_liner", obj.get("one_liner") if isinstance(obj.get("one_liner"), str) else "", 10, 300, problems)
        stack = _bounded("stack", _str_list(obj, "stack", problems), 2, 12, problems)
        screens = _bounded("screens", _str_list(obj, "screens", problems), 1, 10, problems)
        out_of_scope = _bounded("out_of_scope", _str_list(obj, "out_of_scope", problems), 1, 8, problems)
        milestones = _bounded("milestones", _str_list(obj, "milestones", problems), 3, 8, problems)

        raw_entities = obj.get("entities")
        entities: list[Entity] = []
        if not isinstance(raw_entities, list):
            problems.append("entities must be an array of {name, fields} objects")
        else:
            for i, e in enumerate(raw_entities):
                got = Entity.from_dict(e, problems, f"entities[{i}]")
                if got is not None:
                    entities.append(got)
            entities = _bounded("entities", entities, 2, 15, problems)

        raw_endpoints = obj.get("endpoints")
        endpoints: list[Endpoint] = []
        if not isinstance(raw_endpoints, list):
            problems.append("endpoints must be an array of {method, path, purpose} objects")
        else:
            for i, e in enumerate(raw_endpoints):
                got = Endpoint.from_dict(e, problems, f"endpoints[{i}]")
                if got is not None:
                    endpoints.append(got)
            endpoints = _bounded("endpoints", endpoints, 3, 25, problems)

        # Overflow caps, shortfall fails: cap here so the record that survives
        # is always in-bounds.
        entities = entities[:15]
        endpoints = endpoints[:25]

        if problems:
            raise ContractError(stage, problems)
        return cls(
            name=obj["name"], one_liner=obj["one_liner"], stack=stack,
            entities=entities, endpoints=endpoints, screens=screens,
            out_of_scope=out_of_scope, milestones=milestones,
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name, "one_liner": self.one_liner,
            "stack": list(self.stack),
            "entities": [e.to_dict() for e in self.entities],
            "endpoints": [e.to_dict() for e in self.endpoints],
            "screens": list(self.screens),
            "out_of_scope": list(self.out_of_scope),
            "milestones": list(self.milestones),
        }


@dataclass(frozen=True)
class Review:
    """Critic's output: verdict + the revised spec."""

    verdict: str  # ship | revise | blocked
    gaps: list[str]
    risks: list[str]
    confidence: float
    spec: Spec

    _REQUIRED: ClassVar[tuple] = ("verdict", "gaps", "risks", "confidence", "spec")

    @classmethod
    def from_dict(cls, stage: str, obj: Any) -> "Review":
        problems: list[str] = []
        if not isinstance(obj, dict):
            raise ContractError(stage, ["expected a JSON object"])
        missing = [k for k in cls._REQUIRED if k not in obj]
        if "spec" in missing:
            # Name the specific failure the workflow keeps hitting.
            raise ContractError(stage, ["the revised spec must be returned"])
        if missing:
            raise ContractError(stage, [f"missing field '{m}'" for m in missing])

        verdict = obj.get("verdict")
        if verdict not in ("ship", "revise", "blocked"):
            problems.append(
                f"verdict must be ship|revise|blocked, got {verdict!r}"
            )
        gaps = _bounded("gaps", _str_list(obj, "gaps", problems), 1, 8, problems)
        risks = _bounded("risks", _str_list(obj, "risks", problems), 1, 8, problems)

        confidence = obj.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            problems.append("confidence must be a number in [0,1]")
        elif not 0.0 <= float(confidence) <= 1.0:
            problems.append(
                f"confidence must be in [0,1], got {confidence}"
            )

        # A missing or invalid nested spec fails here, at the critic's stage —
        # a Review without a spec is not a review.
        try:
            spec = Spec.from_dict(stage, obj.get("spec"))
        except ContractError as e:
            raise ContractError(stage, [f"revised spec invalid: {e}"]) from None

        if problems:
            raise ContractError(stage, problems)
        return cls(
            verdict=verdict, gaps=gaps, risks=risks,
            confidence=float(confidence), spec=spec,
        )

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict, "gaps": list(self.gaps),
            "risks": list(self.risks), "confidence": self.confidence,
            "spec": self.spec.to_dict(),
        }
