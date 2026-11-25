#!/usr/bin/env bash
# FLUX stage 8 conductor — the "money shot" of the one-take video.
#
# Runs the three live commands in order, in the same terminal, printing what the
# narration should cover while each one runs, then prints the stop cue.
#
# Usage:
#   ./live_proof.sh            # all three commands
#   ./live_proof.sh --run-only # just the single case (for a rehearsal)
#   ./live_proof.sh --mutant-only
#
# Start ./record_take.sh --minutes 55 BEFORE this if you want the screen captured;
# the cue timings below follow the shot list printed by record_take.sh --cue.

set -uo pipefail
cd "$(dirname "$0")/flux-build" || exit 1

MODE="all"
[[ "${1:-}" == "--run-only" ]] && MODE="run"
[[ "${1:-}" == "--mutant-only" ]] && MODE="mutant"

hr() { echo; echo "────────────────────────────────────────────────────────────────"; }

banner() {
  hr
  echo "  $1"
  hr
}

if [[ "$MODE" == "all" || "$MODE" == "run" ]]; then
  banner "1/3 • python run.py run --idea \"a page that tracks plant watering\"  (≈ 63 s)"
  cat <<'CUE'
  NARRATE while it runs:
   · three sub-agents in sequence: Scout → Architect → Critic, typed contracts
     between them — no shared dict, no stringly-typed state
   · deterministic guardrails score first; the LLM judge only answers what
     regex can't
   · one retry round, using the model's own error text

  POINT AT: the verdict line, "critic revised N field(s)", and the call + token
  totals. Then the trace JSON for this run.
CUE
  python3 run.py run --idea "a page that tracks plant watering"
fi

if [[ "$MODE" == "all" ]]; then
  banner "2/3 • python run.py eval  (≈ 16 min)  ← split screen NOW"
  cat <<'CUE'
  NARRATE while it runs — split the screen: this on one side, AGENTS.md and
  guardrails.py / judge.py on the other. Planned beats, in order:

   · the hard rule: a judge that disagrees with a guardrail does not override it
   · the two-tier stack story — pay the model only for taste
   · the baseline policy: it moves only when scores are equal-or-better, never
     to turn a build green
   · judge variance: it is real and visible between runs; say it out loud
   · what the trace JSON holds, and why you keep it

  IF A REGRESSION LINE APPEARS, own it — variance above the 0.03 threshold.
CUE
  python3 run.py eval
fi

if [[ "$MODE" == "all" || "$MODE" == "mutant" ]]; then
  banner "3/3 • python run.py eval --mutant --limit 3  (≈ 6 min)  ← THE SHOT"
  cat <<'CUE'
  SAY: "This is the whole point. I weakened the workflow with a realistic
  simplify PR — trimmed the Critic's revision, told the Architect to be brief.
  The rig scores it zero. An eval suite that can't catch that is decoration."

  IF IT PRINTS A WorkflowError, that is also proof: "the mutant does not just
  score worse, it breaks the contract the guardrails are supposed to catch.
  Either way the case fails and the rig turns red instead of quietly passing it."
CUE
  python3 run.py eval --mutant --limit 3
fi

banner "STOP RECORDING (58:00)"
cat <<'NEXT'
  Wrap, last ~3 min (no commands):
   · AGENTS.md again, then .env.example
   · one line per watch criterion: how you talk to AI, how you orchestrate,
     how you decide, taste
   · close: "This is the harness work the FLUX team does — evals and guardrails
     that keep agents fast, correct and cost-efficient. I'd like to build yours."

  Then:
     ./record_take.sh --normalise <the file>          # fix the audio level
     attach it to the staged draft (EMAIL_TO_BEN.txt) with the CV
     send to ben.syne@directmeds.com before Sat 28 Nov
NEXT