"""LLM-as-judge. Costs money, so it only answers what guardrails cannot.

Three questions, each 0..1, each with a definition the judge must apply rather
than a vibe. The judge sees the idea, the Brief and the final Spec, never the
workflow's prompts or code, or it would score the implementation, not the output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .contracts import Brief, Spec
from .llm import LLM

JUDGE_SYSTEM = """You are a strict reviewer scoring a product spec.
Score each dimension from 0.0 to 1.0. Use the full range; 0.5 means "adequate,
unremarkable". Do not be generous. A high score here should be rare.

completeness
  Does the spec cover the jobs in the brief and every success criterion?
  Every ambiguity the Scout flagged should be answered somewhere in the spec.
  1.0 = nothing in the brief was dropped. 0.0 = large parts are unaddressed.

feasibility
  Could a competent developer build this from the spec as written, starting
  tomorrow, without inventing major decisions? Check that the stack is real and
  coherent, the data model supports the endpoints, and the milestones are
  ordered and independently demoable.
  1.0 = buildable as written. 0.0 = would stall on day one.

taste
  Did someone make decisions, or just list options? Look for: a small stack,
  a real out_of_scope that shows what was refused, entities and fields that
  match the actual problem, and milestones that are scoped to be finished.
  1.0 = clear judgement throughout. 0.0 = generic filler that fits any brief.

Return one JSON object:
  {"completeness": 0.0, "feasibility": 0.0, "taste": 0.0, "reason": "<= 200 chars>"}
"reason" names the single biggest thing holding the score down."""


@dataclass(frozen=True)
class JudgeScore:
    completeness: float
    feasibility: float
    taste: float
    reason: str

    @property
    def average(self) -> float:
        return round((self.completeness + self.feasibility + self.taste) / 3, 4)

    def to_dict(self) -> dict:
        return {
            "completeness": self.completeness,
            "feasibility": self.feasibility,
            "taste": self.taste,
            "average": self.average,
            "reason": self.reason,
        }


def score_spec(llm: LLM, idea: str, brief: Brief, spec: Spec) -> JudgeScore:
    user = (
        "IDEA\n" + idea + "\n\n"
        "BRIEF (produced by an earlier stage)\n" + json.dumps(brief.to_dict(), indent=2) + "\n\n"
        "SPEC TO SCORE\n" + json.dumps(spec.to_dict(), indent=2)
    )
    raw = llm.json(JUDGE_SYSTEM, user, temperature=0)
    return _coerce(raw)


def _coerce(raw: dict) -> JudgeScore:
    def clamp(key: str) -> float:
        value = raw.get(key)
        if not isinstance(value, (int, float)):
            return 0.0
        return max(0.0, min(1.0, float(value)))

    reason = raw.get("reason")
    return JudgeScore(
        completeness=clamp("completeness"),
        feasibility=clamp("feasibility"),
        taste=clamp("taste"),
        reason=reason.strip()[:200] if isinstance(reason, str) else "",
    )
