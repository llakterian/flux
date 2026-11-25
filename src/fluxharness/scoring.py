"""Turn guardrails + judge into one number, then compare against a baseline.

The shape of the score is a deliberate choice:

    hard guardrail failure  -> 0.0, no appeal
    otherwise               -> 0.4 * guardrail_fraction + 0.6 * judge_average

A guardrail failure means the artifact is structurally broken -- the critic
echoed, a secret leaked, the stack is invented. No amount of nice prose earns
that back, so it does not get a vote. Guardrails keep 40% because they are the
part that is free, deterministic and impossible to talk your way out of; the
judge keeps 60% because "is this good" genuinely needs a model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .guardrails import GuardrailReport
from .judge import JudgeScore

HARD_WEIGHT = 0.4
JUDGE_WEIGHT = 0.6

# A metric must fall by more than this before we call it a regression.
DEFAULT_THRESHOLD = 0.03

# Metrics where higher is better and a drop matters.
TRACKED = ("overall", "guardrail_fraction", "completeness", "feasibility", "taste")


@dataclass
class CaseScore:
    case_id: str
    guardrails: GuardrailReport
    judge: JudgeScore | None
    judge_error: str | None = None
    metrics: dict[str, float] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return not self.guardrails.failed

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "metrics": self.metrics,
            "guardrails": self.guardrails.to_dict(),
            "judge": self.judge.to_dict() if self.judge else None,
            "judge_error": self.judge_error,
        }


def compute_metrics(report: GuardrailReport, judge: JudgeScore | None) -> dict[str, float]:
    rules = max(report.rules_run, 1)
    failures = sum(1 for f in report.findings if f.severity == "fail")
    guardrail_fraction = round((rules - failures) / rules, 4)

    if report.failed:
        # Hard gate. The rest is recorded for diagnosis but cannot rescue it.
        overall = 0.0
    else:
        judge_average = judge.average if judge else 0.0
        overall = round(HARD_WEIGHT * guardrail_fraction + JUDGE_WEIGHT * judge_average, 4)

    metrics = {
        "overall": overall,
        "guardrail_fraction": guardrail_fraction,
        "guardrail_hard_fail": 1.0 if report.failed else 0.0,
        "completeness": judge.completeness if judge else 0.0,
        "feasibility": judge.feasibility if judge else 0.0,
        "taste": judge.taste if judge else 0.0,
    }
    return metrics


def aggregate(case_scores: list[CaseScore]) -> dict[str, float]:
    if not case_scores:
        return {m: 0.0 for m in TRACKED}
    out: dict[str, float] = {}
    for metric in TRACKED:
        values = [c.metrics.get(metric, 0.0) for c in case_scores]
        out[metric] = round(sum(values) / len(values), 4)
    out["cases"] = float(len(case_scores))
    out["pass_rate"] = round(sum(1 for c in case_scores if c.passed) / len(case_scores), 4)
    return out


@dataclass(frozen=True)
class Regression:
    metric: str
    baseline: float
    current: float
    drop: float

    def __str__(self) -> str:
        return (
            f"{self.metric}: {self.baseline:.3f} -> {self.current:.3f} "
            f"(drop {self.drop:.3f})"
        )


def compare_to_baseline(
    current: dict[str, float],
    baseline: dict[str, float],
    *,
    threshold: float = DEFAULT_THRESHOLD,
) -> list[Regression]:
    regressions: list[Regression] = []
    for metric in TRACKED:
        if metric not in baseline:
            continue
        before, now = baseline[metric], current.get(metric, 0.0)
        drop = before - now
        if drop > threshold:
            regressions.append(Regression(metric, before, now, round(drop, 4)))
    # Sorted worst-first: the headline number is what a reviewer reads first.
    regressions.sort(key=lambda r: -r.drop)
    return regressions
