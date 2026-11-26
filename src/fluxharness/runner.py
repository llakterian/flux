"""Run the workflow over the dataset, score it, compare to the baseline.

This is the rig. It imports contracts, guardrails, judge and scoring, never
workflow's prompts or internals. It drives Workflow only as a black box that
turns an idea into a Review (AGENTS.md, "The shape").
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .config import Config
from .contracts import Brief, Review, Spec
from .guardrails import run_guardrails
from .judge import score_spec
from .llm import LLM
from .scoring import (
    DEFAULT_THRESHOLD,
    CaseScore,
    aggregate,
    compare_to_baseline,
    compute_metrics,
)
from .workflow import Workflow, WorkflowError

ROOT = Path(__file__).resolve().parents[2]
CASES_PATH = ROOT / "cases" / "dataset.jsonl"
BASELINE_PATH = ROOT / "baselines" / "baseline.json"
RUNS_DIR = ROOT / "runs"


@dataclass
class CaseResult:
    case_id: str
    idea: str
    review: Review
    architect_spec: Spec
    brief: Brief
    trace: list[dict]
    case_score: CaseScore | None = None
    error: str | None = None
    seconds: float = 0.0


@dataclass
class EvalReport:
    mode: str
    started: str
    model: str
    provider: str
    judge_model: str = ""
    results: list[CaseResult] = field(default_factory=list)
    aggregate: dict[str, float] = field(default_factory=dict)
    regressions: list[str] = field(default_factory=list)
    baseline_path: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return not self.error and not self.regressions and all(r.case_score and r.case_score.passed for r in self.results)


def load_cases(path: Path = CASES_PATH) -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    if not cases:
        raise RuntimeError(f"no cases in {path}")
    return cases


def run_case(llm: LLM, case: dict[str, str], *, mutant: bool) -> CaseResult:
    started = time.time()
    workflow = Workflow(llm, mutant=mutant)
    review = workflow.run(case["idea"])

    # Recover the intermediate Brief and the pre-critique Spec from the trace so
    # the rig can score handoffs without reaching into Workflow's internals.
    stages = {t["stage"]: t["output"] for t in workflow.trace}
    brief = Brief.from_dict("trace:scout", stages["scout"])
    architect_spec = Spec.from_dict("trace:architect", stages["architect"])

    return CaseResult(
        case_id=case["id"],
        idea=case["idea"],
        review=review,
        architect_spec=architect_spec,
        brief=brief,
        trace=workflow.trace,
        seconds=round(time.time() - started, 2),
    )


def score_result(llm: LLM, result: CaseResult) -> CaseScore:
    """Score a finished run. Kept separate so fixtures can be scored offline."""
    report = run_guardrails(result.brief, result.review.spec, result.review, result.architect_spec)

    judge = None
    judge_error = None
    try:
        judge = score_spec(llm, result.idea, result.brief, result.review.spec)
    except Exception as exc:  # a judge outage should not lose the guardrail result
        judge_error = f"{type(exc).__name__}: {exc}"

    case_score = CaseScore(
        case_id=result.case_id,
        guardrails=report,
        judge=judge,
        judge_error=judge_error,
    )
    case_score.metrics = compute_metrics(report, judge)
    result.case_score = case_score
    return case_score


def evaluate(
    *,
    mutant: bool = False,
    cases: list[dict[str, str]] | None = None,
    config: Config | None = None,
    on_progress: Callable[[str, int, int], None] | None = None,
    use_judge: bool = True,
) -> EvalReport:
    cfg = config or Config.detect()
    llm = LLM(cfg)
    cases = cases or load_cases()

    report = EvalReport(
        mode="mutant" if mutant else "baseline-run",
        started=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        model=cfg.model,
        provider=cfg.provider,
        judge_model=cfg.effective_judge_model,
    )

    for index, case in enumerate(cases, start=1):
        if on_progress:
            on_progress(case["id"], index, len(cases))
        try:
            result = run_case(llm, case, mutant=mutant)
        except (WorkflowError, Exception) as exc:
            report.results.append(CaseResult(
                case_id=case["id"], idea=case["idea"],
                review=_empty_review(), architect_spec=_empty_spec(),
                brief=_empty_brief(), trace=[],
                error=f"{type(exc).__name__}: {exc}",
            ))
            continue

        if use_judge:
            score_result(llm, result)
        else:
            from .guardrails import GuardrailReport
            from .scoring import CaseScore as CS
            gr = run_guardrails(result.brief, result.review.spec, result.review, result.architect_spec)
            cs = CS(case_id=result.case_id, guardrails=gr, judge=None)
            cs.metrics = compute_metrics(gr, None)
            result.case_score = cs
        report.results.append(result)

    scored = [r for r in report.results if r.case_score]
    report.aggregate = aggregate([r.case_score for r in scored if r.case_score])

    baseline = load_baseline()
    if baseline:
        report.baseline_path = str(BASELINE_PATH)
        report.regressions = [
            str(reg)
            for reg in compare_to_baseline(report.aggregate, baseline, threshold=DEFAULT_THRESHOLD)
        ]

    _write_run(report, llm, mutant)
    return report


def load_baseline(path: Path = BASELINE_PATH) -> dict[str, float] | None:
    if not path.is_file():
        return None
    data = json.loads(path.read_text())
    return data.get("aggregate", data)


def save_baseline(
    report: EvalReport,
    path: Path = BASELINE_PATH,
    previous: dict[str, float] | None = None,
) -> None:
    """Write the baseline.

    `previous` is the aggregate the baseline is replacing. It is kept in the
    file so the history of the instrument is visible: a baseline that moved
    down is not allowed by default, so when it does move (an explicit
    override), the old numbers are still on the record.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "model": report.model,
        "judge_model": report.judge_model,
        "provider": report.provider,
        "saved": report.started,
        "mode": report.mode,
        "aggregate": report.aggregate,
        "cases": [
            {"case_id": r.case_id, "metrics": r.case_score.metrics if r.case_score else None}
            for r in report.results
        ],
    }
    if previous:
        payload["previous_aggregate"] = previous
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _write_run(report: EvalReport, llm: LLM, mutant: bool) -> None:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = RUNS_DIR / f"{'mutant' if mutant else 'eval'}-{stamp}.json"
    path.write_text(json.dumps({
        "mode": report.mode,
        "started": report.started,
        "model": report.model,
        "judge_model": report.judge_model,
        "provider": report.provider,
        "aggregate": report.aggregate,
        "regressions": report.regressions,
        "llm_calls": llm.calls,
        "tokens_in": llm.tokens_in,
        "tokens_out": llm.tokens_out,
        "results": [r.case_id for r in report.results],
        "cases": [
            {
                "case_id": r.case_id,
                "idea": r.idea,
                "error": r.error,
                "seconds": r.seconds,
                "score": r.case_score.to_dict() if r.case_score else None,
                "trace": r.trace,
            }
            for r in report.results
        ],
    }, indent=2) + "\n")


# --- fixtures so the rig can be exercised without a network ----------------
from .contracts import Entity, Endpoint  # noqa: E402  (placed here to keep the header readable)


def _empty_brief() -> Brief:
    return Brief("", [], [], [], [], [])


def _empty_spec() -> Spec:
    return Spec("", "", [], [], [], [], [], [])


def _empty_review() -> Review:
    return Review("blocked", [], [], 0.0, _empty_spec())


def make_fixture_result(case_id: str, idea: str, *, weak: bool = False) -> CaseResult:
    """A canned result used by tests. `weak=True` mimics the mutant's failure."""
    brief = Brief(
        idea=idea,
        users=["a single owner"],
        core_jobs=["record the thing", "see the history"],
        constraints=["works offline", "one operator"],
        ambiguities=["who else can see it"],
        success_criteria=["an owner can log an entry in under 10 seconds"],
    )
    entities = [
        Entity("Entry", ["id", "created_at", "note"]),
        Entity("Owner", ["id", "name"]),
    ]
    endpoints = [
        Endpoint("POST", "/entries", "record a new entry"),
        Endpoint("GET", "/entries", "list entries"),
        Endpoint("GET", "/health", "liveness probe"),
    ]
    spec = Spec(
        name="Fixture",
        one_liner="A minimal tool that records entries and shows their history.",
        stack=["React", "Hono.js", "Cloudflare Workers", "D1"],
        entities=entities,
        endpoints=endpoints,
        screens=["History", "New entry"],
        out_of_scope=[] if weak else ["multi-user sharing", "native mobile app"],
        milestones=["Ship the entry form", "Ship the history view", "Add offline caching"],
    )
    # The mutant's signature: Critic echoes the Architect's spec verbatim.
    architect_spec = spec if weak else Spec(
        name="Fixture",
        one_liner="A minimal tool that records entries and shows their history.",
        stack=["React", "Hono.js", "Cloudflare Workers", "D1"],
        entities=entities,
        endpoints=endpoints,
        screens=["History", "New entry"],
        out_of_scope=["multi-user sharing", "native mobile app", "public profiles"],
        milestones=["Ship the entry form", "Ship the history view", "Add offline caching"],
    )
    review = Review("ship", ["none"], ["low"], 0.9, spec)
    return CaseResult(
        case_id=case_id, idea=idea, review=review,
        architect_spec=architect_spec, brief=brief, trace=[],
    )
