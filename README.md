# fluxharness

**A mini eval harness that scores an AI agent's output and catches regressions.**

One-line idea in, buildable spec out — and a number that says whether the agent
is actually any good.

```
one-line idea -> Scout -> Architect -> Critic -> typed spec + a verdict
```

- **Deterministic guardrails score first.** Ten free rules, same verdict every
  run, no model involved.
- **An LLM judge only answers what regex can't** — composition and taste.
- **Every run compares against a saved baseline**, so "it got worse" is a
  number, not an opinion.

> A judge that disagrees with a guardrail does not override it. If a
> deterministic rule fails, the case scores zero.

```bash
pip install -e .
cp .env.example .env       # add a provider key
pytest -q                  # the rig's own tests, offline, no API key

python run.py run --idea "a page that tracks plant watering"
python run.py eval
python run.py eval --mutant
```

See `AGENTS.md` for how the repo is structured and the rules that must not
break.

MIT licensed.
