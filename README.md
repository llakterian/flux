# fluxharness

**A mini eval harness that scores an AI agent's output and catches regressions.**

One-line idea in, buildable spec out. And a number that says whether the agent
is actually any good.

---

## The problem

A demo proves an agent worked once. It says nothing about whether it works
*reliably*, and nothing at all about whether it got worse after a refactor.
Teams ship agent features on vibes: the output "looked right" in the chat
window, so the PR merged.

fluxharness makes that measurable:

1. **Deterministic guardrails score first.** Ten cheap rules: is the output
   empty, does it contain a forbidden token, is every field present and typed,
   does it exceed the budget. Same input, same verdict, every run, no model
   involved.
2. **An LLM judge only answers what regex can't.** Composition and taste:
   is the spec coherent, is the prose actually usable. The judge is a *separate,
   larger model* from the one under test, so sharing weights cannot flatter
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

cp .env.example .env       # add NVIDIA_API_KEY (or OPENROUTER_API_KEY, etc.)

pytest -q                  # 31 tests, no account or API key needed
```

```bash
python run.py run --idea "a page that tracks plant watering"
python run.py eval
python run.py eval --mutant --limit 2
```

- `run`: one idea, end to end: the verdict, the critic's revisions, the call
  and token counts, and the trace.
- `eval`: the full dataset against the saved baseline, per case.
- `eval --mutant`: the honesty check (see below).

### The baseline only moves sideways or up

Regenerating a baseline whenever the numbers come out lower turns a
regression detector into a mood ring. So the rule is in the code, not in a
README nobody rereads:

- `eval --save-baseline` **refuses** to replace a baseline with lower scores.
- `eval --save-baseline --force` is the explicit override for the one case
  where the numbers are not comparable, **the instrument changed** (a
  different judge model, a different prompt). The replaced aggregate is kept
  in the file under `previous_aggregate`, so the change stays on the record.
- The baseline records the `model` and the `judge_model` that produced it.
  Re-scoring the same code with a different judge is a different measurement,
  not a regression. And the file says so.

---

## The rig refuses to green-wash itself

An eval suite that cannot catch its own regressions is decoration. So the
harness has a **mutation mode**: it deliberately weakens the workflow, trims
the Critic's revision, tells the Architect to be brief. And then runs the
suite against the mutant.

```
overall 0.000   pass rate 0%   regressions vs baseline printed
```

The mutant is not merely worse: the deterministic guardrail
`critic_actually_revised` fires, *"Critic returned the Architect's spec
byte-for-byte; no review happened"*. And the case scores zero. On other
mutants it breaks the contract outright (`[critic] confidence must be a number
in [0,1]`), and the harness reports the failure **by name**. That is also the
proof: the rig catches a realistic simplification PR, not just a random
mutation.

---

## Design decisions worth reading

- **Typed contracts, not prose.** Sub-agents hand each other validated
  records, so a bad stage fails at its own boundary, by name, instead of
  surfacing three stages later as a confusing eval failure.
- **Overflow caps, shortfall fails.** If the model returns ten users and six
  were asked for, keep six and say so. If it returns three, that is a
  failure. Not something to paper over quietly.
- **One repair round, using the model's own error text.** Not "try again":
  the actual validation error, with the offending fields named, and exactly
  one more attempt. A loop that retries forever is a loop that hides a broken
  prompt.
- **User text is data, not instruction.** The one-liner being analysed is
  wrapped in a delimited block and the system prompt says so. Prompt
  injection is a default assumption, not an edge case.
- **The rig never imports the system under test.** `guardrails.py`,
  `judge.py` and `scoring.py` must not know how the workflow is implemented;
  a test reads their source to prove it. The moment a scorer needs to know how
  the output was made, it has started measuring the implementation instead of
  the artifact, which is how eval suites go stale while staying green.

`AGENTS.md` is the longer version of this, and it is the document the tests
hold the code to.

---

## Results from a recorded run

| Check | Result |
|---|---|
| Unit tests | **31 passed**, no account required |
| Model under test | `nvidia/nemotron-3.5-lightning-30b-a3b` (30B, NVIDIA NIM) |
| Judge | `nvidia/nemotron-3-ultra-550b-a55b` (550B), separate and larger; never overrides a guardrail |
| Baseline (8 cases) | overall **0.776**, guardrail fraction **1.000**, completeness 0.513, feasibility 0.606, taste 0.763, pass rate **100 %** |
| Live run (one idea) | 60 to 90 s, 3 model calls, verdict `revise`, critic revised 4 to 5 fields |
| Mutant suite | overall **0.000**, pass rate **0 %**, regressions printed |

### The score moves between runs

The model under test is not deterministic, so the aggregate is a measurement
with a spread, not a value to quote to three decimals. The same code, the same
two models and the same eight cases scored **0.776** when the baseline was
recorded, **0.620** on a re-run and **0.795** on the next one. The guardrails
held at 1.000 in every run, and the low run was rejected by the baseline
guard rather than quietly accepted.

So the baseline is a reference point for a like-for-like comparison, and the
honest claim is the size of the spread, not the third decimal. A regression
means a drop against the baseline **that the same run reproduces**, not a
single lower number.

---

## Layout

```
src/fluxharness/     the harness, workflow.py is the system under test,
                      {guardrails,judge,scoring}.py are the rig
tests/                31 tests, offline, no API key
cases/                8 one-liner ideas
baselines/            the saved baseline, with the model and judge that wrote it
run.py                the CLI
AGENTS.md             how to work in this repo, and the rules that must not break
```

---

## Author

Leonard Sambu, security researcher and full-stack developer, Nairobi, Kenya.

- Portfolio: <https://llakterian.github.io>
- GitHub: <https://github.com/llakterian>
- LinkedIn: <https://linkedin.com/in/cheruiyoot-sambu>

MIT licensed.
