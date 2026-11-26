# AGENTS.md: certified metrics harness

## Mission
Answer business questions from a snapshot of an API I have never used.
Every number comes from a certified metric. No exceptions.

## The gate
- You may READ anything. You may not DEFINE truth.
- Metrics live in `metrics/registry.yaml`. Only a human approves entries.
- No certified metric for a question? Answer `REFUSE: <reason>`. Never estimate.

## Rules I will not relax
- **Count before you sum.** Loaded rows must match the API's own reported total. Mismatch = stop.
- **Never sum a parent total across joined child rows.** One cart, five items, still one total.
- **Money means money charged**, not list price. Name the field and justify it.
- **No writes to source.** The snapshot is read-only after load.
- **Every answer carries a receipt**: metric id, version, row count, snapshot hash.
- **No timestamp, no time series.** If the data has no date, say so and refuse.

## Division of labour
- Subagents: read docs, map fields, propose metrics. They do not compute answers.
- Parent + plain Python: compute, score, report. Deterministic work stays out of the LLM.

## Done means
`/eval` is green and you showed me the output. Not "should work." Show me.
