#!/usr/bin/env python3
"""CLI for the harness.

  python run.py run  --idea "..."     one workflow run, stages printed live
  python run.py eval                  score the dataset against the baseline
  python run.py eval --mutant         prove the rig catches a real regression
  python run.py eval --save-baseline  accept the current scores as 'good'
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from fluxharness.config import Config, ConfigError          # noqa: E402
from fluxharness.runner import (                            # noqa: E402
    BASELINE_PATH,
    evaluate,
    load_baseline,
    load_cases,
    run_case,
    save_baseline,
    score_result,
)
from fluxharness.workflow import Workflow, WorkflowError    # noqa: E402
from fluxharness.llm import LLM                             # noqa: E402
from fluxharness.scoring import baseline_update_allowed     # noqa: E402


class C:
    """Minimal ANSI helpers -- no dependency, no colour unless a TTY."""

    def __init__(self) -> None:
        self.on = sys.stdout.isatty()

    def _wrap(self, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if self.on else text

    def bold(self, t: str) -> str:
        return self._wrap("1", t)

    def dim(self, t: str) -> str:
        return self._wrap("2", t)

    def orange(self, t: str) -> str:
        return self._wrap("38;5;208", t)

    def green(self, t: str) -> str:
        return self._wrap("32", t)

    def red(self, t: str) -> str:
        return self._wrap("31", t)

    def blue(self, t: str) -> str:
        return self._wrap("36", t)


c = C()


def cmd_run(args: argparse.Namespace) -> int:
    try:
        cfg = Config.detect()
    except ConfigError as exc:
        print(c.red(f"error: {exc}"), file=sys.stderr)
        return 2

    llm = LLM(cfg)
    workflow = Workflow(llm, mutant=args.mutant)

    print()
    print(c.bold("  fluxharness") + c.dim(f"  {cfg.provider}/{cfg.model}")
          + c.orange("  [MUTANT]" if args.mutant else ""))
    print(c.dim("  " + "─" * 68))
    print(c.blue("  IDEA   ") + args.idea)
    print(c.dim("  " + "─" * 68))

    try:
        review = workflow.run(args.idea)
    except WorkflowError as exc:
        print(c.red(f"\n  stage failed: {exc}"), file=sys.stderr)
        return 1

    stages = {t["stage"]: t["output"] for t in workflow.trace}

    scout = stages["scout"]
    print(c.orange("\n  1 · SCOUT  ") + c.dim("→ Brief"))
    print(f"     users      {', '.join(scout['users'])}")
    print(f"     jobs       {'; '.join(scout['core_jobs'][:3])}")
    print(f"     ambiguities {len(scout['ambiguities'])} raised")

    arch = stages["architect"]
    print(c.orange("\n  2 · ARCHITECT  ") + c.dim("→ Spec"))
    print(f"     {c.bold(arch['name'])} — {arch['one_liner']}")
    print(f"     stack      {', '.join(arch['stack'])}")
    print(f"     entities   {len(arch['entities'])} · endpoints {len(arch['endpoints'])} · "
          f"screens {len(arch['screens'])}")
    print(f"     refuses    {'; '.join(arch['out_of_scope'])}")

    print(c.orange("\n  3 · CRITIC  ") + c.dim("→ Review + revised Spec"))
    verdict_colour = c.green if review.verdict == "ship" else c.red
    print(f"     verdict    {verdict_colour(review.verdict)}  "
          f"confidence {review.confidence:.2f}")
    print(f"     gaps       {'; '.join(review.gaps)}")
    print(f"     risks      {'; '.join(review.risks)}")

    revised = review.spec.to_dict() == arch
    print()
    if args.mutant:
        print(c.red("     ⚠ mutant mode: critic was told to return the spec unchanged"))
    elif revised:
        print(c.red("     ⚠ critic echoed the architect's spec byte-for-byte"))
    else:
        changed = [k for k in review.spec.to_dict() if review.spec.to_dict()[k] != arch[k]]
        print(c.green(f"     ✓ critic revised {len(changed)} field(s): {', '.join(changed)}"))

    print(c.dim("\n  " + "─" * 68))
    print(c.dim(f"  {llm.calls} calls · {llm.tokens_in} in / {llm.tokens_out} out tokens\n"))
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    try:
        cfg = Config.detect()
    except ConfigError as exc:
        print(c.red(f"error: {exc}"), file=sys.stderr)
        return 2

    mode = c.red("MUTANT") if args.mutant else c.blue("EVAL")
    print()
    print(c.bold("  fluxharness · eval") + c.dim(f"  {cfg.provider}/{cfg.model}")
          + f"  [{mode}]")

    def progress(case_id: str, index: int, total: int) -> None:
        print(c.dim(f"    ({index}/{total}) {case_id} ..."), end="", flush=True)

    # A full eval is ~16 minutes; --limit is the smoke run for rehearsals and
    # live demos where the story matters more than the sample size.
    cases = load_cases()[: args.limit] if args.limit > 0 else None
    report = evaluate(mutant=args.mutant, config=cfg, on_progress=progress,
                      use_judge=not args.no_judge, cases=cases)

    print(c.dim(" done"))
    print(c.dim("  " + "─" * 68))

    if report.error:
        print(c.red(f"  {report.error}"))
        return 1

    for result in report.results:
        if result.error:
            print(f"  {c.red('✗')} {result.case_id:<12} {result.error}")
            continue
        score = result.case_score
        if score is None:
            continue
        mark = c.green("✓") if score.passed else c.red("✗")
        metrics = score.metrics
        print(f"  {mark} {result.case_id:<12} "
              f"overall {metrics['overall']:.3f}  "
              f"guard {metrics['guardrail_fraction']:.2f}  "
              f"comp {metrics['completeness']:.2f} "
              f"feas {metrics['feasibility']:.2f} "
              f"taste {metrics['taste']:.2f}")
        for finding in score.guardrails.findings:
            if finding.severity == "fail":
                print(c.red(f"        ↳ {finding.rule}: {finding.detail}"))
        if score.judge_error:
            print(c.dim(f"        ↳ judge unavailable: {score.judge_error}"))

    agg = report.aggregate
    print(c.dim("  " + "─" * 68))
    print(f"  {c.bold('mean')}   overall {agg['overall']:.3f}   "
          f"pass rate {agg.get('pass_rate', 0):.0%}   "
          f"cases {int(agg.get('cases', 0))}")

    baseline = load_baseline()
    if baseline and not args.mutant:
        print(c.dim(f"  {c.dim('baseline')}  overall {baseline.get('overall', 0):.3f}"))

    if args.save_baseline:
        # A baseline may only move sideways or up. The exception is an
        # explicit --force, for the case where the measuring instrument
        # changed (a different judge model, a different prompt) and the old
        # numbers are history rather than a regression.
        if baseline and not args.force and not baseline_update_allowed(report.aggregate, baseline):
            print(c.red("\n  refusing to replace the baseline: this run scores lower than the saved one."))
            print(c.dim("  A baseline only moves sideways or up. If the instrument changed -- a different"))
            print(c.dim("  judge model, a different prompt -- re-run with --force and say why in the commit."))
            for line in report.regressions:
                print(c.red(f"    ✗ {line}"))
            return 1
        save_baseline(report, previous=baseline if args.force else None)
        print(c.green(f"\n  ✓ baseline saved → {BASELINE_PATH}"))
        if args.force and baseline:
            print(c.dim(f"  (forced — the previous aggregate was overall {baseline.get('overall', 0):.3f}; "
                        f"it is kept in the file under previous_aggregate)"))
    elif report.regressions:
        print(c.red("\n  REGRESSIONS vs baseline:"))
        for line in report.regressions:
            print(c.red(f"    ✗ {line}"))
        print(c.dim(f"\n  baseline: {BASELINE_PATH}"))
        return 1
    elif not baseline:
        print(c.dim("\n  no baseline yet — run with --save-baseline to set one"))

    print()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="fluxharness", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run the workflow once")
    p_run.add_argument("--idea", required=True, help="the vague one-liner")
    p_run.add_argument("--mutant", action="store_true", help="run the degraded variant")
    p_run.set_defaults(func=cmd_run)

    p_eval = sub.add_parser("eval", help="score the dataset")
    p_eval.add_argument("--mutant", action="store_true",
                        help="run the deliberately weakened workflow")
    p_eval.add_argument("--no-judge", action="store_true",
                        help="guardrails only (free, offline after the workflow run)")
    p_eval.add_argument("--save-baseline", action="store_true",
                        help="write the current aggregate as the new baseline")
    p_eval.add_argument("--force", action="store_true",
                        help="allow --save-baseline to replace a baseline with lower scores; "
                             "use only when the instrument changed (a different judge model)")
    p_eval.add_argument("--limit", type=int, default=0, metavar="N",
                        help="score only the first N cases (smoke run)")
    p_eval.set_defaults(func=cmd_eval)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
