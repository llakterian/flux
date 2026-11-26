"""Deterministic guardrails. Free, binary, and first in the scoring order.

They answer questions a regex can answer without lying:
  * did a stage hand off a structurally valid record
  * is the Critic actually revising, or echoing
  * did placeholder text, secrets or boilerplate leak into the output
  * did the spec keep the scope discipline the prompt demanded

A guardrail failure is a hard failure: it zeroes the case regardless of what the
judge thought of the prose.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .contracts import Brief, Review, Spec

# Cheap tells that the model produced filler instead of thinking.
_PLACEHOLDERS = (
    r"\bTODO\b",
    r"\bTBD\b",
    r"\bFIXME\b",
    r"\bXXX\b",
    r"\blorem ipsum\b",
    r"\bcoming soon\b",
    r"\.\.\.$",
)

# "placeholder" and "N/A" are ordinary English in prose -- "the weekly-plan
# feature remains a placeholder" is a critic making a point, not a model
# leaving a hole. They count as filler only when a whole field value is
# nothing but a placeholder.
_FILLER_VALUE = re.compile(
    r"""^(?:
          [\[\(<{]\s*placeholder\s*[\]\)>}]
        | placeholder(?:s)?(?:[\s_-]+(?:text|content|value|name|here|image|title|goes\s+here))?
        | your\s+placeholder\s+here
        | n/?a
    )$""",
    re.IGNORECASE | re.VERBOSE,
)

_SECRET_PATTERNS = (
    (r"(?i)\bsk-[a-z0-9_-]{16,}", "openai-style secret"),
    (r"(?i)\bghp_[a-z0-9]{20,}", "github token"),
    (r"(?i)\bAKIA[0-9A-Z]{16}\b", "aws access key"),
    (r"(?i)\b-----BEGIN [A-Z ]*PRIVATE KEY-----", "private key"),
    (r"(?i)\b(api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?[a-z0-9]{12,}", "hardcoded credential"),
)

# Real, current technology. Anything outside this list is treated as invented.
_KNOWN_TECH = {
    # languages
    "typescript", "javascript", "python", "go", "rust", "solidity", "dart", "sql", "bash",
    "html", "css", "svelte", "vue", "php", "ruby", "java", "c#", "c++", "elixir", "erlang",
    "clojure", "haskell", "kotlin", "swift", "swift ui", "objective-c", "r", "julia", "lua",
    # frontend
    "react", "react 18", "react 19", "next.js", "nextjs", "vite", "sveltekit",
    "tailwind css", "tailwind", "zustand", "recharts", "tanstack", "remix",
    "angular", "angular.js", "alpine.js", "lit", "stencil", "ember.js", "astro",
    "nuxt", "qwik", "jquery", "bootstrap", "shadcn", "antd", "mui", "vuetify",
    "material ui", "chakra ui", "radix ui", "headless ui", "solidjs", "solid",
    "react native", "expo", "ionic", "cordova", "flutter", "unity", "godot",
    # backend / runtime
    "node.js", "nodejs", "bun", "deno", "hono", "hono.js", "express", "express.js",
    "fastapi", "flask", "django", "laravel", "fastify", "gin", "actix",
    "rails", "spring boot", "spring", "phoenix", "slim", "symfony", "nestjs", "koa",
    "uvicorn", "gunicorn", "celery", "bullmq",
    # data
    "postgresql", "postgres", "sqlite", "sqlite3", "mysql", "redis", "prisma", "drizzle",
    "supabase", "firebase", "mongodb", "dynamodb", "turso", "sqlite wasm", "libsql",
    "sqlalchemy", "psycopg", "mongoose", "sequelize", "typeorm", "knex", "knex.js",
    "duckdb", "clickhouse", "cassandra", "couchdb", "elasticsearch", "meilisearch",
    "typesense", "opensearch", "influxdb", "timescaledb", "mariadb", "cockroachdb",
    "planetscale", "neon", "xata", "upstash", "upstash redis",
    # cloud / infra
    "cloudflare workers", "cloudflare pages", "cloudflare d1", "cloudflare kv",
    "cloudflare r2", "cloudflare durable objects", "workers", "pages", "d1",
    "vercel", "vercel edge", "netlify", "aws", "aws lambda", "lambda", "gcp",
    "azure", "docker", "docker compose", "kubernetes", "k8s", "fly.io", "render",
    "railway", "wrangler", "terraform", "pulumi", "ansible", "helm", "github actions",
    "circleci", "gitlab ci", "jenkins", "serverless", "heroku", "digitalocean",
    "cloudflare", "cloudflare edge", "supabase edge", "firebase auth", "firebase hosting",
    # auth / payments / messaging
    "jwt", "oauth", "oauth2", "clerk", "auth0", "stripe", "resend", "sendgrid",
    "postmark", "twilio", "ses", "razorpay", "paystack", "supabase auth",
    # ai
    "openai", "anthropic", "claude", "groq", "gemini", "ollama", "llama",
    "openrouter", "mistral", "cohere", "hugging face", "transformers",
    "pytorch", "tensorflow", "keras", "numpy", "pandas", "scikit-learn", "sklearn",
    "jupyter", "notebook", "opencv", "langchain", "langgraph",
    # misc
    "pwa", "service workers", "workbox", "websockets", "sse", "graphql",
    "trpc", "zod", "vitest", "jest", "playwright", "cypress", "pytest",
    "rxjs", "d3", "chart.js", "echarts", "pdfkit", "puppeteer",
    "ffmpeg", "webrtc", "indexeddb", "openapi", "swagger", "grpc", "protobuf",
    "sentry", "posthog", "plausible", "umami", "socket.io", "axios",
    "three.js", "threejs", "phaser", "processing", "p5.js",
    "db", "database", "kv", "r2", "blob storage", "scikit learn", "worker",
    # mobile / alternative frontends
    "htmx", "astro", "nuxt", "qwik", "bootstrap", "shadcn", "antd", "mui", "vuetify",
    # backend / queues / search
    "axios", "sequelize", "typeorm", "mongoose", "knex",
    "nestjs", "koa", "uvicorn", "gunicorn", "celery", "bullmq",
    "kafka", "rabbitmq", "nats", "elasticsearch", "meilisearch",
    "typesense", "clickhouse", "duckdb",
    # tooling / infra
    "npm", "pnpm", "yarn", "webpack", "esbuild", "rollup", "nx", "turbo",
    "nginx", "caddy", "grafana", "prometheus", "opentelemetry",
    "postman", "insomnia", "curl",
    # ai / retrieval
    "pgvector", "langchain", "langgraph", "llamaindex", "chroma", "qdrant",
    "weaviate", "pinecone", "milvus",
    # payments / messaging
    "plaid", "whatsapp", "telegram", "html5", "css3", "sass",
}

_PLACEHOLDER_RE = re.compile("|".join(_PLACEHOLDERS), re.IGNORECASE | re.MULTILINE)


@dataclass
class Finding:
    rule: str
    detail: str
    severity: str = "fail"  # fail -> zeroes the case; warn -> does not


@dataclass
class GuardrailReport:
    _RULE_NAMES = (
        "no_placeholder_text",
        "no_leaked_secrets",
        "critic_actually_revised",
        "names_what_it_refuses",
        "stack_is_real",
        "entities_unique",
        "endpoints_unique",
        "milestones_ordered",
        "ambiguities_resolved",
        "verdict_matches_confidence",
    )

    findings: list[Finding] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return any(f.severity == "fail" for f in self.findings)

    @property
    def rules_run(self) -> int:
        return len(self._RULE_NAMES)

    def to_dict(self) -> dict:
        return {
            "passed": not self.failed,
            "rules_run": self.rules_run,
            "failures": [f.__dict__ for f in self.findings if f.severity == "fail"],
            "warnings": [f.__dict__ for f in self.findings if f.severity == "warn"],
        }


def run_guardrails(brief: Brief, spec: Spec, review: Review, architect_spec: Spec | None = None) -> GuardrailReport:
    """architect_spec is passed in so we can check the Critic really revised."""
    report = GuardrailReport()
    add = report.findings.append

    _check_placeholders(brief, spec, review, add)
    _check_secrets(spec, review, add)
    _check_echo(report, spec, architect_spec, add)
    _check_scope_discipline(spec, add)
    _check_stack_real(spec, add)
    _check_shape(spec, add)
    _check_consistency(brief, spec, review, add)

    return report


def _check_placeholders(brief: Brief, spec: Spec, review: Review, add) -> None:
    blobs = [
        ("brief", brief.to_dict()),
        ("spec", spec.to_dict()),
        ("review", {k: v for k, v in review.to_dict().items() if k != "spec"}),
    ]
    for label, obj in blobs:
        for hit in sorted({m.group(0) for m in _PLACEHOLDER_RE.finditer(_flatten(obj))}):
            add(Finding("no_placeholder_text", f"{label} contains filler: {hit!r}"))
        # "placeholder" as prose is the noun, not filler. It is filler only
        # when a whole field value is nothing but a placeholder.
        for value in _string_values(obj):
            if _FILLER_VALUE.match(value.strip()):
                add(Finding("no_placeholder_text", f"{label} contains filler: {value.strip()!r}"))


def _check_secrets(spec: Spec, review: Review, add) -> None:
    blob = _flatten({"spec": spec.to_dict(), "review": review.to_dict()})
    for pattern, label in _SECRET_PATTERNS:
        match = re.search(pattern, blob)
        if match:
            add(Finding("no_leaked_secrets", f"{label} in output: {match.group(0)[:12]!r}..."))


def _check_echo(report: GuardrailReport, spec: Spec, architect_spec: Spec | None, add) -> None:
    """The Critic must change something. Echoing back is the classic silent failure."""
    if architect_spec is None:
        return
    if spec.to_dict() == architect_spec.to_dict():
        add(Finding(
            "critic_actually_revised",
            "Critic returned the Architect's spec byte-for-byte; no review happened",
        ))
    else:
        # Counted so a "changed one space" cheat still shows as minimal work.
        changed = sum(
            1 for key in spec.to_dict()
            if spec.to_dict()[key] != architect_spec.to_dict().get(key)
        )
        if changed == 1 and spec.out_of_scope == architect_spec.out_of_scope:
            add(Finding(
                "critic_actually_revised",
                f"Critic changed only {changed} field; revision looks cosmetic",
                severity="warn",
            ))


def _check_scope_discipline(spec: Spec, add) -> None:
    if not spec.out_of_scope:
        add(Finding("names_what_it_refuses", "out_of_scope is empty"))
        return
    thin = [s for s in spec.out_of_scope if len(s.split()) < 3]
    if thin:
        add(Finding(
            "names_what_it_refuses",
            f"{len(thin)} out_of_scope entry(ies) too thin to be a decision: {thin!r}",
            severity="warn",
        ))


# Hallucination signatures. A coinage built from these morphemes and absent
# from the known list is a framework the model made up: "QuantumFluxDB",
# "HyperCache", "DataForge". Real technology that starts with the same words
# ("InfluxDB", "Datadog") is in the known list and never reaches this check.
_HALLUCINATION_MARKS = (
    "quantum", "neural", "forge", "synapse", "turbo", "ultra", "mega",
    "hyperscale", "chatbot", "fluxdb", "fluxorm", "aiforge", "aiflow",
    "nextquantum", "quantumdb", "hypercache", "neuralcache",
)


def _check_stack_real(spec: Spec, add) -> None:
    """Catch invented technology without punishing unfamiliar real technology.

    An allowlist of every technology that exists cannot be maintained: it
    would flag every tool added since the list was written, and a false
    positive here zeroes a case whose output was fine. So the known list
    identifies technology we recognise, and anything outside it is judged by
    its shape. A coinage built from hallucination morphemes is invented
    (hard fail); anything else is merely unfamiliar (warning).
    """
    invented: list[str] = []
    unfamiliar: list[str] = []
    for tech in spec.stack:
        if _is_known_tech(tech):
            continue
        if any(mark in _normalise_tech(tech) for mark in _HALLUCINATION_MARKS):
            invented.append(tech)
        else:
            unfamiliar.append(tech)
    if invented:
        add(Finding("stack_is_real", f"invented technology: {invented}"))
    if unfamiliar:
        add(Finding(
            "stack_is_real",
            f"unrecognised technology (not on the known list): {unfamiliar}",
            severity="warn",
        ))


# "React 18", "Next.js 15", "PostgreSQL (managed)" must match the same
# technology as their bare name, version and packaging noise is not
# invention. Invented names still fail: they have nothing to normalise to.
_VERSION_NOISE = re.compile(r"\s*\([^)]*\)|\s+v?\d+(?:\.\d+)*(?:\s+(?:lts|latest))?$", re.IGNORECASE)

# Hyphen, underscore and slash all mean "space" in a stack name:
# "cloudflare-workers", "cloudflare_workers" and "Cloudflare Workers" are
# one technology, not three.
_SEPARATORS = re.compile(r"[-_/]+")

# Qualifiers that describe a technology without changing what it is.
# "Vanilla JavaScript" is JavaScript; "Plain CSS" is CSS. Stripping these
# lets the bare technology be looked up without inventing new entries.
_QUALIFIERS = (
    "vanilla", "plain", "bare", "simple", "basic", "modern", "classic",
    "native", "serverless", "static", "lightweight", "minimal", "custom",
)

# Name endings that are part of the technology's own name.
_NAME_SUFFIXES = ("3", "js", "lang")

# Extensions that are packaging, not identity: "vue.js" is Vue.
_PACKAGING_SUFFIXES = (".js", ".ts", ".jsx", ".tsx", ".py", ".rb", ".mjs")

# A version glued to the name: "python3.11", "go1.22", "node20".
_GLUED_VERSION = re.compile(r"\d+(?:\.\d+)*$")

# Spellings that mean the same technology as a bare name.
_NAME_ALIASES = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "jsonschema": "json schema",
    "postgres": "postgresql",
    "mongo": "mongodb",
    "k8s": "kubernetes",
    "cf": "cloudflare workers",
    "golang": "go",
    "tsjs": "typescript",
    "cshtml": "html",
    "scss": "sass",
    "reactjs": "react",
    "vuejs": "vue",
    "sveltejs": "svelte",
    "angularjs": "angular",
    "tailwindcss": "tailwind css",
    "dockercompose": "docker compose",
    "githubactions": "github actions",
    "cloudflareworker": "cloudflare workers",
    "workerskv": "cloudflare kv",
    "cloudflarepages": "cloudflare pages",
    "cloudflarer2": "cloudflare r2",
    "firebaseauth": "firebase auth",
    "supabaseedge": "supabase edge",
    "verceledge": "vercel edge",
    "mongod": "mongodb",
    "mysql8": "mysql",
    "redis7": "redis",
    "flutter": "flutter",
    "swiftui": "swift ui",
    "node": "node.js",
    "mongodb": "mongodb",
    "scikitlearn": "scikit-learn",
    "svelte": "svelte",
    "next": "next.js",
    "astro": "astro",
    "remix": "remix",
    "vite": "vite",
    "express": "express",
    "django": "django",
    "laravel": "laravel",
    "fastapi": "fastapi",
    "flask": "flask",
    "prisma": "prisma",
    "drizzle": "drizzle",
    "supabase": "supabase",
    "firebase": "firebase",
    "vercel": "vercel",
    "netlify": "netlify",
    "cloudflare": "cloudflare workers",
}


def _normalise_tech(raw: str) -> str:
    t = _VERSION_NOISE.sub("", raw.strip()).strip().lower()
    t = _SEPARATORS.sub(" ", t)
    t = " ".join(t.split())
    return t or raw.strip().lower()


def _tech_candidates(raw: str) -> set[str]:
    """Every spelling of this technology we should accept.

    A name is real if it matches a known technology under any of its ordinary
    spellings. Invented names ("QuantumFluxDB") produce no candidate that is
    known, so they still fail.
    """
    base = _normalise_tech(raw)
    candidates = {base}

    parts = base.split()
    # Drop leading qualifiers: "vanilla html" -> "html".
    if len(parts) > 1 and parts[0] in _QUALIFIERS:
        candidates.add(" ".join(parts[1:]))
    # Drop a trailing qualifier: "html vanilla" -> "html".
    if len(parts) > 1 and parts[-1] in _QUALIFIERS:
        candidates.add(" ".join(parts[:-1]))
    # "sqlite3" -> "sqlite"; "nodejs" -> "node".
    for index, part in enumerate(parts):
        for suffix in _NAME_SUFFIXES:
            if part.endswith(suffix) and len(part) > len(suffix):
                stripped = list(parts)
                stripped[index] = part[: -len(suffix)]
                candidates.add(" ".join(stripped))
    # Common abbreviations and alternate spellings.
    for index, part in enumerate(parts):
        if part in _NAME_ALIASES:
            aliased = list(parts)
            aliased[index] = _NAME_ALIASES[part]
            candidates.add(" ".join(aliased))
    # Packaging is not identity: "vue.js" -> "vue".
    for index, part in enumerate(parts):
        for suffix in _PACKAGING_SUFFIXES:
            if part.endswith(suffix) and len(part) > len(suffix):
                stripped = list(parts)
                stripped[index] = part[: -len(suffix)]
                candidates.add(" ".join(stripped))
    # A glued version is not identity: "python3.11" -> "python".
    for index, part in enumerate(parts):
        stripped_part = _GLUED_VERSION.sub("", part)
        if stripped_part and stripped_part != part:
            stripped = list(parts)
            stripped[index] = stripped_part
            candidates.add(" ".join(stripped))
    return candidates


def _is_known_tech(raw: str) -> bool:
    for candidate in _tech_candidates(raw):
        if candidate in _KNOWN_TECH:
            return True
        # Apply aliases to the candidate too: "vanilla js" strips to "js",
        # which only becomes "javascript" through the alias table.
        parts = candidate.split()
        if len(parts) == 1 and parts[0] in _NAME_ALIASES:
            if _NAME_ALIASES[parts[0]] in _KNOWN_TECH:
                return True
    # A joined pair of real technologies ("d1-sqlite", "docker-compose")
    # names real technology even when the compound itself is not listed.
    parts = _normalise_tech(raw).split()
    if len(parts) < 2:
        return False
    if all(_is_known_tech(part) for part in parts):
        return True
    # "next 14", "node 20": a real technology plus a version number.
    if len(parts) == 2 and _GLUED_VERSION.fullmatch(parts[1]):
        return _is_known_tech(parts[0])
    return False


def _check_shape(spec: Spec, add) -> None:
    if len({e.name.lower() for e in spec.entities}) != len(spec.entities):
        add(Finding("entities_unique", "duplicate entity names"))
    paths = [(e.method, e.path) for e in spec.endpoints]
    if len(set(paths)) != len(paths):
        add(Finding("endpoints_unique", "duplicate method+path pairs"))
    if len(spec.milestones) < 3:
        add(Finding("milestones_ordered", f"only {len(spec.milestones)} milestone(s), need >= 3"))


def _check_consistency(brief: Brief, spec: Spec, review: Review, add) -> None:
    """Every ambiguity the Scout raised must be answered somewhere downstream."""
    if not brief.ambiguities:
        return
    spec_blob = _flatten(spec.to_dict()).lower()
    unanswered = [
        a for a in brief.ambiguities
        if not any(word.lower() in spec_blob for word in a.split()[:3] if len(word) > 3)
    ]
    if unanswered:
        add(Finding(
            "ambiguities_resolved",
            f"{len(unanswered)} of {len(brief.ambiguities)} ambiguities never addressed in the spec",
            severity="warn",
        ))
    if review.verdict == "ship" and review.confidence < 0.5:
        add(Finding(
            "verdict_matches_confidence",
            f"verdict='ship' with confidence={review.confidence}",
        ))


def _flatten(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_flatten(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_flatten(v) for v in value)
    return str(value)


def _string_values(value) -> list[str]:
    """Every string leaf, so a field can be judged on its own terms."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _string_values(v)]
    if isinstance(value, (list, tuple)):
        return [s for v in value for s in _string_values(v)]
    return []
