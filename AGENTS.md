# AGENTS.md — how to work in this repo

This repo answers one question: **can an agent be made dependable?**
Everything here is either a system under test, or the rig that tests it.

## The shape

Two halves. Never mix them.

| Half | Path | Job |
|---|---|---|
| **System under test** | `src/fluxharness/workflow.py` | Three sub-agents that turn a vague one-liner into a buildable spec |
| **The rig** | `src/fluxharness/{guardrails,judge,scoring}.py` | Score the output, catch regressions |
| **The driver** | `src/fluxharness/runner.py`, `run.py` | Drive the workflow as a black box, aggregate, compare to baseline |

**Hard rule: `guardrails.py`, `judge.py` and `scoring.py` never import from
`workflow.py`.** The driver may *call* the workflow — it has to — but the code
that decides whether output is good must not know how that output was made. The
moment a scorer needs to know how the workflow is written, it has stopped
measuring the product and started measuring the implementation. That is how evals
go stale while staying green. `tests/test_regression.py` enforces this by reading
the source.

## Contracts are the handoff

Sub-agents do not pass prose to each other. They pass **typed records** defined in
`contracts.py`, validated on the way out of one stage and on the way into the next.

- An agent that cannot produce a valid record **fails loudly at its own stage**,
  not three stages later when someone reads garbage.
- Add a field → update the contract, the guardrail that checks it, and the
  baseline. All three, in the same change. A field no eval looks at is a field
  that will silently rot.

## When you change the workflow

1. Run `python run.py eval` against the current baseline. Note the scores.
2. Make the change.
3. Run `python run.py eval --mutant` if you suspect the change weakened output;
   otherwise re-run plain `eval`.
4. Commit `baselines/baseline.json` **only** when the new scores are equal or
   better and you can say why.

Never regenerate the baseline to make a red build green. The baseline is the
memory of what "good" looked like. Rewriting it erases the regression you were
hired to catch.

## Guardrails vs. the judge

- **Guardrails** (`guardrails.py`) are deterministic and free. They catch
  structural failure: unparseable JSON, missing keys, placeholder text, leaked
  secrets, out-of-range values. They are binary and they are not negotiable.
- **The judge** (`judge.py`) is an LLM and costs money. It covers what regex
  cannot: is this feasible, is it complete, does it read like a person thought
  about it.

Prefer a guardrail. Reach for the judge only when you have already exhausted
what you can check for free. A guardrail that runs in 0ms and never hallucinates
beats a judge that scores 0.9 on a confident lie.

### One guardrail is two-tiered

`stack_is_real` used to hard-fail any technology missing from `_KNOWN_TECH`.
An allowlist of everything that exists cannot be maintained: it flagged real
tools the list had not heard of (`Preact`, `Flutter`, `GitHub Pages`), and a
false positive there zeroes a case whose output was fine — the rig scoring its
own ignorance as a product defect.

So it now separates the two cases. A coinage built from hallucination
morphemes (`QuantumFluxDB`, `HyperCache`, `DataForge`) is invented: hard fail.
Anything else that is merely unfamiliar is reported as a **warning**. The
judge's `feasibility` score independently checks that the stack is real, so
losing the hard fail on rare tools loses no coverage — and the guardrail still
catches the failure it was built for, for free.

## Talking to the model

- One JSON object per response. `response_format` where the endpoint supports it;
  a strict parse + one retry where it does not.
- Prompts live next to the stage they drive, as module-level constants. No
  prompt is ever built by string concatenation from user input.
- **User text is data, not instruction.** The one-liner being analysed is
  interpolated into a delimited block and the system prompt says so. This is a
  security tool built by a security researcher; treat prompt injection as a
  default assumption, not an edge case.

## Running things

```bash
python run.py run  --idea "a page that tracks plant watering"   # one workflow run
python run.py eval                                            # score dataset vs baseline
python run.py eval --mutant                                    # prove the rig catches a regression
pytest -q                                                      # the rig's own tests
```

`eval` needs `OPENROUTER_API_KEY`, `GROQ_API_KEY` or `OPENAI_API_KEY`.
`pytest` needs nothing — the regression tests run against fixtures and must
never hit the network.

### The model is a reasoning model

It spends completion tokens thinking before it emits content. Starve the
budget and you get `finish_reason: "length"` with an empty body — a failure
that looks like the model ignored you. `max_tokens` is 8000 for that reason, and
`llm.py` retries a starved completion with double the budget instead of
repeating the same starved question.

## Voice

Write like the code: state the tradeoff, then stop. If a comment explains *what*
the next line does, delete it. If it explains *why this and not the obvious
alternative*, keep it — that is the part that does not survive in git blame.
