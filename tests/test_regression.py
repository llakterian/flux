"""The rig's own tests. Offline, no network, no API key.

The point of this file is not coverage. It is to prove the two claims the repo
makes: the rig catches a real regression, and the rig stays decoupled from the
system it measures.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fluxharness.contracts import Brief, ContractError, Entity, Endpoint, Review, Spec  # noqa: E402
from fluxharness.guardrails import run_guardrails                     # noqa: E402
from fluxharness.runner import (                                        # noqa: E402
    EvalReport,
    make_fixture_result,
    save_baseline,
    score_result,
)
from fluxharness.scoring import (                                     # noqa: E402
    CaseScore,
    aggregate,
    baseline_update_allowed,
    compare_to_baseline,
    compute_metrics,
)


# --------------------------------------------------------------------------
# 1. The headline: the rig catches the regression it was built to catch.
# --------------------------------------------------------------------------
def test_mutant_signature_is_caught_by_a_free_guardrail():
    """The Critic echoing the Architect's spec must fail, deterministically."""
    good = make_fixture_result("ok", "track plant watering", weak=False)
    weak = make_fixture_result("bad", "track plant watering", weak=True)

    good_report = run_guardrails(good.brief, good.review.spec, good.review, good.architect_spec)
    weak_report = run_guardrails(weak.brief, weak.review.spec, weak.review, weak.architect_spec)

    assert not good_report.failed, [f.rule for f in good_report.findings if f.severity == "fail"]
    assert weak_report.failed
    assert "critic_actually_revised" in {f.rule for f in weak_report.findings}


def test_hard_guardrail_failure_zeroes_the_score():
    """Nice prose must not rescue a structurally broken artifact."""
    weak = make_fixture_result("bad", "track plant watering", weak=True)
    report = run_guardrails(weak.brief, weak.review.spec, weak.review, weak.architect_spec)

    class FakeJudge:
        completeness = feasibility = taste = 1.0
        average = 1.0

    metrics = compute_metrics(report, FakeJudge())
    assert metrics["overall"] == 0.0, "a perfect judge score must not override a hard fail"
    assert metrics["guardrail_hard_fail"] == 1.0


def test_healthy_artifact_scores_and_passes():
    good = make_fixture_result("ok", "track plant watering", weak=False)
    report = run_guardrails(good.brief, good.review.spec, good.review, good.architect_spec)
    metrics = compute_metrics(report, None)

    assert not report.failed
    assert metrics["overall"] > 0
    # Judge absent -> overall is entirely the guardrail's 40% share.
    assert metrics["overall"] == pytest.approx(0.4 * metrics["guardrail_fraction"], abs=1e-6)


# --------------------------------------------------------------------------
# 2. Individual guardrails -- the free checks, each proven to bite.
# --------------------------------------------------------------------------
def _brief() -> Brief:
    return Brief(
        idea="track plant watering",
        users=["a household"],
        core_jobs=["log a watering", "see when each plant was last watered"],
        constraints=["works offline"],
        ambiguities=["can two people share one list"],
        success_criteria=["log an entry in under 10 seconds"],
    )


def _spec(**overrides) -> Spec:
    base = dict(
        name="Watering Log",
        one_liner="Log when each plant was watered and show the last date.",
        stack=["React", "Cloudflare Workers", "D1"],
        entities=[],
        endpoints=[],
        screens=["History"],
        out_of_scope=["multi-user sharing"],
        milestones=["Form", "History view", "Offline caching"],
    )
    base.update(overrides)
    return Spec(**base)


def test_placeholder_text_is_caught():
    spec = _spec(one_liner="A TODO tool for plants. TBD when it works.")
    report = run_guardrails(_brief(), spec, Review("ship", ["x"], ["y"], 0.9, spec), spec)
    assert "no_placeholder_text" in {f.rule for f in report.findings}


def test_leaked_secret_is_caught():
    spec = _spec(stack=["React", "Cloudflare Workers", "D1"],
                 one_liner="Uses sk-abc123def456ghi789jkl012mn345pqr for auth.")
    report = run_guardrails(_brief(), spec, Review("ship", ["x"], ["y"], 0.9, spec), spec)
    assert "no_leaked_secrets" in {f.rule for f in report.findings}


def test_invented_technology_is_caught():
    spec = _spec(stack=["React", "QuantumFluxDB", "D1"])
    report = run_guardrails(_brief(), spec, Review("ship", ["x"], ["y"], 0.9, spec), spec)
    assert "stack_is_real" in {f.rule for f in report.findings}


def test_real_technology_spellings_are_not_invented():
    """Real tech written in an ordinary spelling must not be scored as invented.

    A hard fail here zeroes a case whose output was fine -- the model wrote
    "Cloudflare Workers" with a hyphen, not a fake framework.
    """
    real = [
        "SQLite3", "cloudflare-workers", "d1-sqlite", "vanilla-html",
        "Vanilla JavaScript", "Postgres", "Flask", "htmx", "FastAPI",
        "React 18", "Next.js 15", "PostgreSQL (managed)", "vanilla js",
        "vue.js", "python3.11", "node 20", "go1.22", "tailwindcss",
        "docker-compose", "github-actions", "workers kv", "firebase auth",
        "mongo db", "next 14", "scikit-learn", "nodejs", "postgres 16",
    ]
    spec = _spec(stack=real)
    report = run_guardrails(_brief(), spec, Review("ship", ["x"], ["y"], 0.9, spec), spec)
    assert "stack_is_real" not in {f.rule for f in report.findings}, [
        f.detail for f in report.findings if f.rule == "stack_is_real"
    ]


def test_invented_technology_names_are_still_caught():
    """Expanding the known list must not make it stop catching fakes.

    The allowlist grows with real technology; a plausible-sounding invented
    name still has to fail.
    """
    for fake in ("QuantumFluxDB", "FluxORM", "HyperCache", "QuantumDB",
                 "NeuralCache", "DataForge", "QuantumMesh", "TurboDB",
                 "QuantumForge", "NextQuantum", "UltraMesh"):
        spec = _spec(stack=["React", fake, "D1"])
        report = run_guardrails(_brief(), spec, Review("ship", ["x"], ["y"], 0.9, spec), spec)
        assert "stack_is_real" in {f.rule for f in report.findings}, f"{fake} was accepted"


def test_unfamiliar_real_technology_warns_instead_of_zeroing():
    """A tool the known list has not heard of must not zero a good case.

    The allowlist cannot enumerate every technology that exists. A rare but
    real tool gets a warning; only a coinage built from hallucination
    morphemes is a hard failure.
    """
    spec = _spec(stack=["React", "Deno", "Bun", "Astro", "Elixir", "Nostr"])
    revised = _spec(
        stack=["React", "Deno", "Bun", "Astro", "Elixir", "Nostr"],
        one_liner="Log when each plant was watered and show the last date, offline.",
    )
    report = run_guardrails(_brief(), revised, Review("ship", ["x"], ["y"], 0.9, revised), spec)
    assert not report.failed, [f.detail for f in report.findings if f.severity == "fail"]
    warned = [f for f in report.findings if f.rule == "stack_is_real" and f.severity == "warn"]
    assert warned, "unfamiliar technology should still be reported"


def test_placeholder_noun_in_prose_is_not_filler():
    """"remains a placeholder" is a critic's point, not an unfilled field."""
    review = Review(
        "blocked",
        ["the weekly-plan feature remains a placeholder; tests cannot verify it"],
        ["none"],
        0.8,
        _spec(),
    )
    report = run_guardrails(_brief(), _spec(), review, _spec())
    assert "no_placeholder_text" not in {f.rule for f in report.findings}, [
        f.detail for f in report.findings if f.rule == "no_placeholder_text"
    ]


def test_placeholder_as_a_whole_field_value_is_filler():
    """The rule still bites: a field whose whole value is a placeholder."""
    spec = _spec(screens=["History", "placeholder"])
    report = run_guardrails(_brief(), spec, Review("ship", ["x"], ["y"], 0.9, spec), spec)
    assert "no_placeholder_text" in {f.rule for f in report.findings}


def test_starved_completion_is_distinguished_from_an_empty_one():
    """A reasoning model that ran out of budget is not the same as a refusal.

    Retrying with the same budget reproduces the same starvation, so the
    client has to widen it.
    """
    from fluxharness.llm import CompletionStarved, LLMError

    assert issubclass(CompletionStarved, LLMError)
    assert CompletionStarved is not LLMError, "starvation needs its own branch"


def test_empty_out_of_scope_is_a_failure():
    spec = _spec(out_of_scope=[])
    report = run_guardrails(_brief(), spec, Review("ship", ["x"], ["y"], 0.9, spec), spec)
    assert "names_what_it_refuses" in {f.rule for f in report.findings}


def test_ship_below_half_confidence_is_inconsistent():
    spec = _spec()
    report = run_guardrails(_brief(), spec, Review("ship", ["x"], ["y"], 0.2, spec), spec)
    assert "verdict_matches_confidence" in {f.rule for f in report.findings}


def test_every_guardrail_rule_can_still_fire():
    """A rule nobody exercises is a rule that quietly stops working.

    Rebuilds a deliberately awful artifact that trips all ten rules at once and
    asserts the set of fired rules matches the declared set exactly -- so a rule
    that stops firing (or a new one added without a test) fails here.
    """
    from fluxharness.guardrails import GuardrailReport

    bad_spec = Spec(
        name="Bad",
        one_liner="TODO tool using sk-abc123def456ghi789jkl012mn345pqr for auth",
        stack=["React", "QuantumFluxDB"],          # invented tech
        entities=[Entity("Item", ["id"]), Entity("Item", ["id"])],   # duplicates
        endpoints=[                                 # duplicate method+path
            Endpoint("GET", "/x", "a"),
            Endpoint("GET", "/x", "b"),
        ],
        screens=["One"],
        out_of_scope=[],                            # refuses nothing
        milestones=["only", "two"],                 # under the floor
    )
    # Critic echoes the Architect verbatim, and ships it while barely sure.
    report = run_guardrails(
        _brief(), bad_spec,
        Review("ship", ["gap"], ["risk"], 0.3, bad_spec),
        bad_spec,
    )
    fired = {f.rule for f in report.findings}
    assert fired == set(GuardrailReport._RULE_NAMES), (
        f"unexercised rules: {set(GuardrailReport._RULE_NAMES) - fired}; "
        f"undeclared rules: {fired - set(GuardrailReport._RULE_NAMES)}"
    )


# --------------------------------------------------------------------------
# 3. Baseline comparison -- a drop is a regression, a rise is not.
# --------------------------------------------------------------------------
def test_drop_beyond_threshold_is_flagged():
    baseline = {"overall": 0.80, "taste": 0.70, "completeness": 0.90,
                "feasibility": 0.90, "guardrail_fraction": 1.0}
    current = dict(baseline, overall=0.55, taste=0.60)

    found = compare_to_baseline(current, baseline, threshold=0.03)
    metrics = [r.metric for r in found]
    assert "overall" in metrics
    assert "taste" in metrics
    assert "completeness" not in metrics, "unchanged metrics are not regressions"
    assert found[0].metric == "overall", "worst drop sorts first"


def test_improvement_is_not_a_regression():
    baseline = {"overall": 0.50, "taste": 0.40}
    current = {"overall": 0.90, "taste": 0.80}
    assert compare_to_baseline(current, baseline) == []


def test_tiny_jitter_within_threshold_is_ignored():
    baseline = {"overall": 0.80}
    current = {"overall": 0.78}  # drop of 0.02 < 0.03
    assert compare_to_baseline(current, baseline, threshold=0.03) == []


def test_aggregate_is_mean_over_scored_cases():
    def case(cid, overall):
        cs = CaseScore(case_id=cid, guardrails=run_guardrails(
            _brief(), _spec(), Review("ship", ["x"], ["y"], 0.9, _spec()), _spec()), judge=None)
        cs.metrics = {"overall": overall, "guardrail_fraction": 1.0,
                      "completeness": 0.0, "feasibility": 0.0, "taste": 0.0}
        return cs

    agg = aggregate([case("a", 0.4), case("b", 0.8)])
    assert agg["overall"] == pytest.approx(0.6)
    assert agg["cases"] == 2


# --------------------------------------------------------------------------
# 4. Contracts -- a malformed handoff fails at its own stage, by name.
# --------------------------------------------------------------------------
def test_contract_names_the_offending_field():
    with pytest.raises(ContractError) as exc:
        Spec.from_dict("architect", {"name": "x"})
    assert exc.value.stage == "architect"
    assert "missing field" in str(exc.value)


def test_contract_rejects_out_of_range_confidence():
    with pytest.raises(ContractError):
        Review.from_dict("critic", {
            "verdict": "ship", "gaps": ["a"], "risks": ["b"],
            "confidence": 7, "spec": _spec().to_dict(),
        })


def test_contract_rejects_invalid_http_verb():
    bad = _spec().to_dict()
    bad["endpoints"] = [{"method": "FETCH", "path": "/x", "purpose": "nope"}]
    with pytest.raises(ContractError):
        Spec.from_dict("architect", bad)


def test_contract_rejects_missing_required_stage_output():
    with pytest.raises(ContractError):
        Brief.from_dict("scout", {"idea": "track plants"})


def test_contract_caps_overflow_but_fails_on_shortfall():
    """Too many items is a size problem; too few is a did-not-do-the-job problem."""
    payload = {
        "idea": "track plant watering",
        "users": ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"],
        "core_jobs": ["do one thing", "do another thing"],
        "constraints": ["offline"],
        "ambiguities": ["who can see this list"],
        "success_criteria": ["log an entry fast", "see the history"],
    }
    brief = Brief.from_dict("scout", payload)
    assert len(brief.users) == 6, "overflow must be capped to the contract max"

    payload["core_jobs"] = ["only one"]
    with pytest.raises(ContractError) as exc:
        Brief.from_dict("scout", payload)
    assert "at least 2" in str(exc.value)


# --------------------------------------------------------------------------
# 5. The architectural rule, enforced by reading the source.
# --------------------------------------------------------------------------
def test_scoring_modules_never_import_the_system_under_test():
    """AGENTS.md: the rig must not know how the workflow is written.

    If guardrails/judge/scoring start reaching into workflow.py, they begin
    measuring the implementation instead of the artifact -- which is exactly how
    an eval suite rots while staying green.
    """
    rig = ["guardrails.py", "judge.py", "scoring.py"]
    for name in rig:
        source = (ROOT / "src" / "fluxharness" / name).read_text()
        assert "from .workflow" not in source, f"{name} imports the system under test"
        assert "import workflow" not in source, f"{name} imports the system under test"


def test_dataset_is_wellformed():
    lines = [json.loads(l) for l in (ROOT / "cases" / "dataset.jsonl").read_text().splitlines() if l.strip()]
    assert len(lines) >= 6, "too few cases to catch a regression"
    ids = [c["id"] for c in lines]
    assert len(ids) == len(set(ids)), "duplicate case ids"
    for case in lines:
        assert case["idea"].strip(), f"{case['id']} has an empty idea"
        assert len(case["idea"].split()) <= 20, f"{case['id']} idea is not a one-liner"


def test_baseline_records_which_judge_produced_it(tmp_path):
    """The judge is part of the measuring instrument.

    Re-scoring the same code with a different judge is a different
    measurement, not a regression. So the baseline has to say which judge
    wrote it -- otherwise two baselines get compared as if they were the
    same instrument.
    """
    report = EvalReport(
        mode="baseline-run",
        started="2026-01-01T00:00:00+00:00",
        model="model-under-test",
        provider="test-provider",
        judge_model="judge-model",
    )
    report.aggregate = {"overall": 0.8}

    path = tmp_path / "baseline.json"
    save_baseline(report, path)
    saved = json.loads(path.read_text())

    assert saved["judge_model"] == "judge-model"
    assert saved["model"] == "model-under-test"
    assert saved["provider"] == "test-provider"


def test_the_baseline_only_moves_sideways_or_up():
    """AGENTS.md: never regenerate the baseline to turn a build green.

    The rule is enforced in code, not in a README nobody rereads: the CLI
    refuses to replace a baseline with lower scores unless the operator
    explicitly says the instrument changed.
    """
    baseline = {"overall": 0.8, "feasibility": 0.6, "completeness": 0.5, "taste": 0.7}

    assert baseline_update_allowed({"overall": 0.8}, baseline), "equal is allowed"
    assert baseline_update_allowed({"overall": 0.9}, baseline), "better is allowed"
    assert baseline_update_allowed({"overall": 0.79}, baseline), "inside the threshold is allowed"
    assert not baseline_update_allowed({"overall": 0.5}, baseline), "a real drop is refused"
    assert baseline_update_allowed({"overall": 0.5}, None), "no baseline yet is allowed"


def test_a_forced_rebaseline_keeps_the_old_numbers(tmp_path):
    """When the baseline is replaced anyway, the old aggregate stays on the record."""
    report = EvalReport(
        mode="baseline-run",
        started="2026-01-01T00:00:00+00:00",
        model="model-under-test",
        provider="test-provider",
        judge_model="judge-model",
    )
    report.aggregate = {"overall": 0.7}

    path = tmp_path / "baseline.json"
    save_baseline(report, path, previous={"overall": 0.9})
    saved = json.loads(path.read_text())

    assert saved["aggregate"]["overall"] == 0.7
    assert saved["previous_aggregate"]["overall"] == 0.9


def test_agent_md_exists_and_states_the_hard_rule():
    text = (ROOT / "AGENTS.md").read_text()
    assert "never import from" in text and "workflow.py" in text
    assert "Never regenerate the baseline" in text


def test_cli_is_importable():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "run.py"), "--help"],
        capture_output=True, text=True, cwd=ROOT,
    )
    assert proc.returncode == 0, proc.stderr
    assert "eval" in proc.stdout
