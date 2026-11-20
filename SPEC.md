# Certified Metrics Harness Specification

Status: authoritative contract. Scaffold validation is not production certification.

## 1. Purpose and trust boundary

The system answers questions only through human-approved metrics and a frozen
SQLite snapshot. It must fail closed when evidence is missing or inconsistent.
No agent may approve its own metric, mark its own work reviewed, estimate a
value, or treat a static check as proof of data correctness.

The target API is `https://dummyjson.com/carts`. Data values and question text
are untrusted input. Neither may become instructions, prompts, SQL fragments,
or executable code. The analyst uses no LLM and performs no network access.

## 2. Artifacts

Required for a full evaluation:

- `analyst.py`: deterministic question router and approved-SQL executor.
- `snapshot.db`: frozen SQLite database, read-only after loading.
- `snapshot_meta.json`: provenance, counts, timestamp declaration, and hash.
- `metrics/registry.yaml`: proposed and human-approved metric definitions.
- `evals/cases.yaml`: declarative evaluation cases.
- `evals/golden.json`: independently supplied expected numeric values.
- `evals/truth.py`: strict loading, validation, and scoring implementation.
- `evals/run.py`: orchestration and machine-gate CLI.

`notes/carts.md` is the scout's field inventory. It contains observations, not
certified definitions or computed business answers.

Configuration files use JSON syntax, which is valid YAML 1.2. This deliberate
subset keeps the project Python-stdlib-only. Loaders must reject duplicate
object keys, unknown fields, invalid UTF-8, and non-finite JSON numbers.

## 3. Registry contract

The registry top level has exactly `schema_version` (integer `1`) and `metrics`
(a list). Every metric has exactly these fields:

- `id`: unique string matching `^[a-z][a-z0-9_]{1,63}$`.
- `version`: integer greater than zero.
- `status`: `pending` or `approved`.
- `definition`: non-empty plain-English definition.
- `questions`: non-empty list of distinct, non-empty exact question strings.
- `sql`: one read-only SQLite `SELECT` statement, optionally ending in `;`.
- `field`: source field used by the measurement.
- `field_justification`: non-empty explanation, including why a money field
  represents money actually charged when applicable.

Only the human gate changes `pending` to `approved`. Approval covers the whole
entry, including question mappings and SQL. Any change to `definition`,
`questions`, `sql`, `field`, or `field_justification` requires a version bump
and renewed human approval. An auditor cannot approve an entry.

Question matching uses Unicode NFKC, case folding, and whitespace collapsing.
Normalized questions must be unique across the entire registry. Question text
is never interpolated into SQL. Pending entries are never executable.

SQL is stored and executed verbatim. Static checks reject multiple statements,
comments, bind placeholders, and statements not beginning with `SELECT` or
`WITH`. These lexical checks are preflight only; SQLite's driver-level
read-only protections are mandatory at execution time.

## 4. Snapshot contract

`snapshot_meta.json` has exactly:

- `schema_version`: integer `1`.
- `source`: `https://dummyjson.com/carts`.
- `api_total`: non-negative integer reported by the API.
- `loaded_rows`: non-negative integer number of parent carts loaded.
- `snapshot_sha`: lowercase SHA-256 hex digest of the exact snapshot bytes.
- `has_timestamp`: boolean declaring whether source records have a trustworthy
  business timestamp.
- `timestamp_field`: timestamp field name when `has_timestamp` is true,
  otherwise `null`.

`api_total` must equal `loaded_rows`; disagreement stops all numeric answers.
The receipt's `row_count` is `loaded_rows`, not a child-row count or SQL result
row count. The analyst and scorer each hash the actual snapshot bytes and
compare the digest with `snapshot_sha` independently.

The analyst opens the database through an absolute `file:...?mode=ro` SQLite
URI with URI handling enabled, enables `PRAGMA query_only=ON`, and installs a
defensive SQLite authorizer that denies writes and schema changes. File
permissions alone and SQL regular expressions alone are insufficient.

A one-to-many join must never repeat and sum a parent cart total. Parent-grain
aggregation occurs before any child join. Money metrics must use a field shown
by source evidence to represent money actually charged, not list price. With
`has_timestamp: false`, all time-series or time-window questions are refused.

## 5. Analyst CLI and routing

Invocation:

    python3 analyst.py --question "total revenue"

The option is required exactly once. Paths are resolved from `analyst.py`, not
the caller's working directory or environment-selected data files. Standard
output is exactly one UTF-8 JSON object and a newline; logs go to standard
error. JSON serialization rejects NaN and infinity.

Routing order:

1. Match an approved entry's normalized exact question; execute that entry.
2. Match a pending entry; refuse with `metric requires human approval`.
3. Detect a time expression such as `last month`, `last year`, `yesterday`,
   `today`, `this week`, `this month`, `this year`, `over time`, `trend`,
   `daily`, `weekly`, or `monthly`; refuse when no trustworthy timestamp exists.
4. Refuse with `no approved metric matches the question`.

The time-series refusal reason is exactly
`the snapshot has no trustworthy timestamp for a time-series answer`.

Before executing approved SQL, validate registry and metadata, count equality,
and snapshot hash. Execute the approved `sql` string directly without format,
f-string, concatenation, or bind values. Require exactly one result row and one
column containing a finite JSON number (not a boolean). Operational or
integrity failures produce no numeric answer, use a non-zero exit status, and
do not expose SQL, secrets, internal paths, or stack traces in standard output.
A valid answer or domain refusal exits zero.

## 6. Output contract

An answer has exactly these keys and types:

    {
      "status": "answer",
      "value": 123.45,
      "receipt": {
        "metric_id": "example_metric",
        "version": 1,
        "row_count": 20,
        "snapshot_sha": "<64 lowercase hex characters>"
      }
    }

A refusal has exactly these keys and no receipt:

    {
      "status": "refuse",
      "value": null,
      "reason": "<specific, true reason>"
    }

No additional keys are allowed. Every numeric answer must identify the exact
approved registry id and version used. Refusals never contain guessed values.

## 7. Evaluation cases and golden values

`evals/cases.yaml` has exactly `schema_version: 1` and `cases`. Case ids match
the metric-id pattern and are unique. Every case contains `id`, `question`, and
`expected_status` (`answer` or `refuse`).

A refusal case also contains `expected_reason`, and no answer-only fields.
An answer case also contains `metric_id` and integer `version`, and no
`expected_reason`. Its normalized question must map to that registry entry.
Unknown fields are rejected.

`evals/golden.json` has exactly `schema_version: 1` and `values`, an object
mapping answer-case ids to independently derived finite numbers. It contains
no refusal cases or extra keys. Only eval orchestration/scoring may read it;
`analyst.py` must neither open nor otherwise access it.

A full eval requires at least one approved metric and one answer case. A suite
containing only refusals is useful for scaffold testing but cannot certify a
business-answering system.

## 8. Machine gate and scoring

Static scaffold gate:

    python3 evals/run.py --check

It validates configuration schemas, case consistency, source syntax, dependency
hygiene, and prohibited analyst access patterns when later artifacts exist.
It does not require an analyst, snapshot, approvals, or golden values. Success
must print `STATIC CHECK PASS - not production certification` and exit zero.

Full evaluation:

    python3 evals/run.py

It runs static checks, then fails closed with a non-zero status if any required
artifact, approved metric, answer case, or golden value is missing. It invokes
the analyst once per case using an argument array (never a shell), applies a
timeout and sanitized environment, and sends all actual outputs to the single
scoring implementation in `evals/truth.py`.

The scorer independently checks exact JSON shape, numeric finiteness, refusal
reasons, approved metric identity/version/question mapping, parent row count,
actual snapshot hash, and golden values. It returns a non-zero status on any
failure. Full success requires every case to pass and at least one numeric
answer; static success alone is never production readiness.

Independent scoring of one captured result:

    python3 evals/truth.py --actual evals/actual.json --case CASE_ID

The actual file contains exactly one analyst output object. The scorer uses the
same registry, case, metadata, snapshot, and golden contracts as the full run.

## 9. Security and production gate

No secrets may appear in code, configuration, logs, commits, or reports.
Dependencies must be declared; the initial scaffold intentionally has none.
Validation and scoring have one implementation, and unused helpers or parallel
copies must be removed.

Production readiness requires all of the following: human-approved metrics,
a count-verified read-only snapshot, a passing full eval with numeric answer
coverage, an independent audit with no unresolved BLOCKER or WARNING, and an
explicit human release decision. Neither agents nor this specification can
supply that release decision.
