# Finance Agent — Design

Status: **approved**
Traces to: `SPEC.md`

How the approved specification is realised. Repository conventions — naming,
file responsibilities, dependency management — live with the repository's
contributor conventions and are not repeated here.

---

## 1. Architecture

Two independently deployable services sharing no code. The only contract
between them is HTTP.

```
                    ┌──────────────────────────────┐
  browser ────────► │  dashboard  (Streamlit)      │
                    │  charts · chat · upload      │
                    │  holds NO credentials        │
                    └──────────────┬───────────────┘
                                   │  HTTP/JSON (server-to-server)
                                   ▼
                    ┌──────────────────────────────┐
                    │  agent_service  (FastAPI)    │
                    │  parse · categorise · answer │
                    │  owns ALL credentials        │
                    └───────┬──────────────┬───────┘
                            │              │
                            ▼              ▼
                    ┌──────────────┐  ┌──────────┐
                    │    MySQL     │  │  Gemini  │
                    └──────────────┘  └──────────┘
```

**Why two services.** It puts a hard boundary around credentials (SPEC §1,
NFR-11). The dashboard cannot reach the database or the model even by mistake,
because it has neither the credentials nor the client libraries. Duplicating a
little code across the boundary is the accepted cost.

**Why no CORS.** The browser only ever talks to the dashboard. The dashboard's
*server* calls the agent service, so no cross-origin request is ever made.
CORS middleware here would be dead code implying browser clients that do not
exist.

### Layering within the agent service

```
HTTP routes            ── request/response, status codes, no business logic
   ↓
orchestration          ── import pipeline, period inference, transactions
   ↓
agent capabilities     ── extraction, categorisation, tool calling, query generation
   ↓
data access            ── every query, one place
   ↓
MySQL
```

Each layer depends only downward. The agent layer never touches HTTP; the data
layer never knows a model exists.

---

## 2. Components

| Component | Responsibility | Spec |
|---|---|---|
| **HTTP API** | Routes, validation, status codes, background scheduling | §8 |
| **Import orchestration** | Extraction → period inference → duplicate check → categorisation → persistence | §4 |
| **Extraction** | Statement bytes → transaction records | §4.2 |
| **Categorisation** | Four-tier assignment, pure enrichment — it commits nothing | §5 |
| **Tool layer** | Typed queries offered to the model; executes and sanitises results | §6.1–6.4 |
| **Query generation** | Fallback for questions no typed query answers, with validation | §6.5 |
| **Model gateway** | Every model call passes through it: retry, backoff, error summarisation | §9.1 |
| **Job store** | Import progress; in-process, bounded, not durable | §4.6 |
| **Session store** | Conversation memory per session; in-process, bounded, not durable | §6.6 |
| **Data access** | All queries; money formatting; the missing-data contract | §3 |
| **Rule repair** | Re-applies current rules after a rule change | §5.6 |
| **Tracing** | Records model requests and user actions as traces | §10.1 |

Two rules hold the layering together: **categorisation commits nothing** — the
orchestration layer owns persistence, so a failed import writes nothing (BR-7);
and **every model call goes through the gateway**, so retry policy and error
wording exist in exactly one place.

---

## 3. Data model

```
category ──┬─< keyword_rule
           ├─< merchant
           ├─< monthly_summary
           └─< transaction >── bank_statement
```

| Table | Holds | Key constraint |
|---|---|---|
| `category` | Fixed vocabulary, type, display colour | unique name |
| `keyword_rule` | Description pattern → category, with precedence | unique keyword |
| `merchant` | Learned exact description → category | unique raw name |
| `bank_statement` | One import | **unique (month, year)** |
| `transaction` | One statement line plus how it was categorised | — |
| `monthly_summary` | Precomputed totals per category per period | unique (year, month, category) |

### Decisions worth stating

**Amounts are positive; `direction` carries the sign.** Storing signed amounts
would make every aggregate depend on the sign being right at write time. With
direction separate, "spending" is a filter rather than a convention.

**The unique constraint on `(statement_month, statement_year)` is the duplicate
protection.** Not application logic — the database refuses it, so a race cannot
produce two statements for one period (SPEC §4.4).

**`monthly_summary` is a cache.** Every value is derivable from `transaction`.
It exists so the dashboard renders without aggregating on each page load, and
is rebuilt wholesale for a period whenever that period's data changes.
Rebuilding beats incremental updates because a recategorisation moves spend
between categories.

**`categorization_method` and `user_confirmed` together encode trust.** The
review queue is exactly the rows where the model decided and the user has not
confirmed. Merchant memory is written only from trusted rows (BR-4).

**Known wart:** `transaction_date` is a `VARCHAR(10)` holding `YYYY-MM-DD`
rather than a `DATE`. It sorts correctly and period filtering uses a prefix
match, but it cannot use an index efficiently and supports no date arithmetic.
Irrelevant at present volume; the first thing to change if volume grows.

---

## 4. Key flows

### 4.1 Import

```
POST file
   │  validate type and emptiness            (synchronous, fast)
   ├──────────────────────────────────► 202 + job id
   │
   └─ background, own database session:
         render every page → extract transactions
         infer period (modal month)
         reject if period already present
         categorise (enrichment only)
         write statement + transactions + summary
         one commit
         mark job done / failed
```

**The background worker opens its own database session.** The request-scoped
session is closed when the `202` is sent; reusing it would fail intermittently
and confusingly.

**Acceptance is synchronous, work is not.** Validation happens before the job
exists, so a bad file fails immediately rather than becoming a failed job.

### 4.2 Question

```
message + session id + viewed period
   │
   ├─ fetch available periods and category names   (database, cheap)
   ├─ get or create the session's conversation
   ├─ send: today's date + viewed period + question
   │
   ├─ model returns a tool request ──► execute ──► send result back ──► answer
   ├─ model answers directly (greeting, or out of scope)
   └─ model declines ──────────────► generated query path
```

Periods and category names are injected into the conversation at creation.
Without the category list the model guesses names that do not exist, spending a
round trip per guess.

The per-message prefix states today's date and labels the viewed period as *the
view, not the meaning of "this month"*. Instructions adjacent to the question
outweigh instructions further away; the prefix and the standing instructions
must therefore agree.

---

## 5. Interfaces

### 5.1 Between services

HTTP/JSON, as specified in SPEC §8. Money crosses this boundary twice: once
numeric (for charts) and once formatted (for display and for the model).

### 5.2 Between the system and the model

Three distinct uses, each with its own model:

| Use | Frequency | Why separate |
|---|---|---|
| Extraction | once per import | Vision; largest payload |
| Categorisation | at most once per unseen description | Cheap bulk classification |
| Conversation | twice per question | Tool calling; highest frequency |

**Free-tier request quota is enforced per project per model**, so separating by
role multiplies the usable daily budget. Each is independently configurable
without a rebuild, so an exhausted model can be swapped for a working one.

**The model never receives a bare monetary number.** Results are transformed so
money appears only as formatted strings. Given a bare float a model renders it
in whatever currency it assumes — the formatted string removes the choice
(BR-1).

---

## 6. Failure handling

| Failure | Design response |
|---|---|
| Transient model unavailability | Retry with exponential backoff and jitter |
| Short-window rate limit | Retry, honouring the stated delay |
| Daily quota exhausted | Fail immediately — retrying cannot succeed and consumes budget |
| Model unavailable to the account | Fail immediately — a configuration error, not a transient one |
| Network interruption | Retry |
| Malformed model output | Treat as a failed classification; flag the transaction |
| Database unreachable at startup | Refuse to start, naming host and database |
| Import failure at any stage | Roll back; the job records which of three reasons applied |

Classification of failures into *retryable* and *not* lives in one place, so
the policy cannot drift between call sites.

Errors reaching the user are summarised to one sentence naming the cause. The
full detail is available at increased verbosity but never surfaced.

---

## 7. State and scaling

Two stores are deliberately in-process and bounded:

| Store | Bound | Lost on restart |
|---|---|---|
| Import jobs | most recent N | yes |
| Conversations | N turns, then restart | yes |

**Both are acceptable losses.** A job is progress tracking; the durable record
of an import is the statement. A conversation is short-term memory; durable
knowledge is in the database, where it can be corrected. A stored transcript
would preserve conclusions that later corrections invalidate.

**Consequence, stated plainly:** the agent service assumes a single worker. Two
processes behind a load balancer would not share sessions, so a follow-up could
land on a worker with no history. Scaling horizontally means moving the session
store to Redis or pinning sessions to workers. This is a deliberate
simplification for a single-user system, not an oversight.

---

## 8. Security

| Concern | Design response | Spec |
|---|---|---|
| Credential exposure | Only the agent service holds credentials | NFR-11 |
| Query injection | Parameterised access throughout; untrusted values never composed into query text | BR-9 |
| Model-generated queries | Allowlist: read-only, must read a table, bounded, real category names. Refused if any rule fails | §6.5 |
| Financial data in logs | Amounts and descriptions only at increased verbosity | NFR-14 |
| Financial data in version control | Statement files excluded; only synthetic samples committed | NFR-15 |

**Transaction descriptions are untrusted input.** They are model output derived
from an uploaded file — about as untrusted as input gets — and are treated
accordingly wherever they reach the database.

The generated-query validator is an **allowlist, not a blocklist**. Anything
that is not a bounded read-only query reading a real table is refused rather
than sanitised, because sanitising generated SQL is a losing game.

---

## 9. Observability

At default verbosity, each question records: the question, each query with its
arguments and row count, duration, and the route taken. Each log line carries a
short session trace prefix.

**Arguments are logged deliberately.** A wrong argument is the most common
failure — a category that does not exist, a period the user did not mean — and
it is invisible from a well-formed answer alone.

**Financial detail is DEBUG-only**, so default logs can be shared when
reporting a problem.

**Falling back to a generated query is a warning**, because a recurring warning
means a typed query is missing. Adding one is preferable to improving query
generation: typed queries are cheaper, deterministic, and cannot be malformed.

---

## 9a. Tracing

Tracing attaches at the **model gateway** — the single function every model call
already passes through. One attachment point covers extraction, categorisation,
conversation, and query generation, and the retry loop is inside it, so retries
appear as part of the request they belong to rather than as separate events.

A second attachment at the request boundary opens a trace per user action, so a
chat question appears as one trace with its model requests nested beneath it.
Without this, two model requests answering one question would look unrelated.

```
request: POST /chat  ─────────────── trace
   ├─ model request: select tool  ── generation  (model, tokens, latency)
   ├─ database query              ── span
   └─ model request: phrase answer ─ generation  (model, tokens, latency)
```

**Tracing is strictly non-blocking and non-fatal.** Trace delivery is
asynchronous, and any failure to record is swallowed: an unreachable or
misconfigured trace destination must never turn a working answer into an error.
The system starts and runs normally with tracing disabled.

**Redacted at the boundary, not at the collector.** Prompts and results carry
transaction descriptions and amounts, so a redaction function runs inside this
process before any span is exported (NFR-20). Amounts in any format, every
float, and all free-text fields are replaced; periods, categories, counts,
token usage, and timing survive.

Redacting here rather than trusting the collector means the guarantee holds
wherever traces are sent, and it fails closed: an unrecognised type is dropped
rather than risked. The self-hosted alternative was rejected because Langfuse
v3+ needs roughly six services — disproportionate for a single-user system.

**Why here rather than logs.** Logs already record the shape of the work —
tool name, arguments, row count, duration. What they cannot show is token
usage and cost per request, which is precisely the quantity BR-8 and NFR-9
constrain. Tracing measures the thing the specification bounds.

## 10. Testing

| Layer | Approach |
|---|---|
| Pure logic | Direct tests, no fixtures |
| Schema-dependent logic | In-memory SQLite built from the same models |
| Model interaction | Substituted; no test ever calls the model |
| Instruction content | Assert governing rules are present |

**SQLite in tests is the single documented exception** to MySQL-only, and
applies to tests alone. It exists so the suite runs on a fresh clone with no
database, no key, and no network (NFR-16, NFR-17).

**Instruction-content tests are a weak but deliberate guard.** They cannot
prove the model obeys a rule; they stop a rule being deleted by accident. Each
documents the failure it prevents. SPEC §13 records this limitation rather than
implying the criteria are fully verified.

---

## 11. Deployment

Three containers: database, agent, dashboard. Tracing is configured by
environment and needs no container — the collector is external and receives
only redacted data. The agent waits for the database
to report healthy, then seeds idempotently before serving. Data persists in a
named volume.

Model selection, log verbosity, and tracing configuration pass through as
optional environment overrides, so behaviour can change without a rebuild.
Tracing is off unless configured, so the system runs unchanged without it. Only the agent container
receives credentials; the dashboard receives only the API URL — the credential
boundary is enforced by the orchestration, not merely by convention.
