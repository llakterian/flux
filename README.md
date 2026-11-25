# fluxharness

**A mini eval harness that scores an AI agent's output and catches regressions.**

Built for the DirectMeds FLUX application (Nairobi, November 2026). One-line
idea in, buildable spec out — and a number that says whether the agent is
actually any good.

---

## The problem

A demo proves an agent worked once. It says nothing about whether it works
*reliably*, and nothing at all about whether it got worse after a refactor.
Teams ship agent features on vibes: the output "looked right" in the chat
window, so the PR merged.

fluxharness makes that measurable:

1. **Deterministic guardrails score first.** Ten cheap rules — is the output
   empty, does it contain a forbidden token, is every field present and typed,
   does it exceed the budget. Same input, same verdict, every run, no model
   involved.
2. **An LLM judge only answers what regex can't.** Composition and taste —
   is the spec coherent, is the prose actually usable. The judge is a *separate,
   stronger model* from the one under test, so sharing weights cannot flatter
   the output.
3. **Every run compares against a saved baseline.** A regression is not "the
   score is low"; it is "the score dropped against the version we shipped".

### The rule that matters

> A judge that disagrees with a guardrail does not override it.

If a deterministic rule fails, the run scores zero. No amount of eloquent
judge output rescues it. The expensive half of the harness can be wrong about
taste; it can never be wrong about a hard failure.

---

## Architecture

```
one-line idea
      │
      ▼
   Scout  ──▶ IdeaSpec        (what is being asked for)
      │
      ▼
Architect ──▶ BuildSpec      (the buildable spec: typed records, not prose)
      │
      ▼
  Critic  ──▶ Review         (score, verdict, per-field revisions)
```

Each stage passes **typed records**, not prose. A stage that produces garbage
fails at its own boundary, by name, not three stages later. There is one repair
round: the workflow catches the model's own error text and retries once.

| Module | What it does |
|---|---|
| `contracts.py` | The typed handoffs (`IdeaSpec`, `BuildSpec`, `Review`). A stage that emits the wrong shape fails here. |
| `workflow.py` | The three system prompts and the run loop, including the single repair round. |
| `guardrails.py` | The ten deterministic rules. Free to run, and they never hallucinate. |
| `judge.py` | The LLM judge: composition and taste only. |
| `scoring.py` | The 40/60 weighting, and the "any guardrail fail ⇒ overall 0.0" rule. |
| `runner.py` | The black-box driver: same call in, same score out, every time. |
| `config.py` / `llm.py` | A thin client and the `(system, user)` JSON signature the harness chats with. |

---

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .

cp .env.example .env       # add OPENROUTER_API_KEY

pytest -q                  # 28 tests, no account or API key needed
```

```bash
python run.py run --idea "a page that tracks plant watering"
python run.py eval
python run.py eval --mutant --limit 3
```

- `run` — one idea, end to end: the verdict, the critic's revisions, the call
  and token counts, and the trace.
- `eval` — the full dataset against the saved baseline, per case.
- `eval --mutant` — the honesty check (see below).

---

## The rig refuses to green-wash itself

An eval suite that cannot catch its own regressions is decoration. So the
harness has a **mutation mode**: it deliberately weakens the workflow — trims
the Critic's revision, tells the Architect to be brief — and then runs the
suite against the mutant.

```
overall 0.000   pass rate 0%   regressions vs baseline printed
```

The mutant is not merely worse; on the watering case it breaks the contract
outright (`[critic] confidence must be a number in [0,1]`), and the harness
reports the failure **by name**. That is also the proof: the rig catches a
realistic simplification PR, not just a random mutation.

---

## Results from the recorded run

| Check | Result |
|---|---|
| Unit tests | 28 passed, no account required |
| Live run (one idea) | 63 s, 3 model calls, 1822 in / 10508 out tokens, verdict `revise`, critic revised 4 fields |
| Mutant suite | overall **0.000**, pass rate **0 %**, regressions printed |
| Judge | separate, stronger model; never overrides a guardrail |

---

## The one-take build video

The application email is a **20–60 minute continuous screen recording** of
this build, narrated live, no cuts. The file is attached to the GitHub
release for this repository:

<https://github.com/llakterian/flux/releases>

It is the same code in this repository, recorded in one pass: the contract
handoffs, the three prompts, the ten guardrails, the two-tier scoring, the
test suite, a live run, and the mutant proof.

The recording rig is in the repository too (`record_take.sh`, `live_proof.sh`):
it picks a microphone, runs a three-second level check, records screen and
audio with a gain trim and a limiter, and prints an `ffprobe` sanity report.

---

## Contact

Sambu Leonard — full-stack developer and security researcher, Nairobi, Kenya.

- Portfolio: <https://llakterian.github.io>
- GitHub: <https://github.com/llakterian>
- LinkedIn: <https://linkedin.com/in/cheruiyoot-sambu>
