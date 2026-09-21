# Finance Agent — Specification

Status: **approved**
Traces to: `requirements.md`

This document defines **what the system must do** — observable behaviour,
business rules, validation, error handling, and acceptance criteria. It does
not prescribe how to build it; implementation conventions are kept with the
repository's contributor guidance.

---

## 1. Scope

The system ingests South African bank statements, categorises the transactions,
stores them, and answers natural-language questions about them. It presents the
same data visually.

It has two parts. The **agent service** is the backend: it owns all data, all
credentials, and all model access. The **dashboard** is the frontend: it renders
what the backend returns and holds no credentials of its own. They are packaged
and deployed separately, and the only contract between them is the HTTP API in
§8.

There is no authentication. Every request is treated as coming from the single
account holder (`requirements.md` A-1). No behaviour in this document is
conditional on identity or permission.

---

## 2. Domain concepts

| Concept | Meaning |
|---|---|
| **Statement** | One imported bank statement, unique per calendar month |
| **Period** | A (month, year) pair. The unit all reporting is grouped by |
| **Transaction** | One line from a statement: date, description, amount, direction, fee, balance |
| **Direction** | `DR` money leaving the account, `CR` money arriving. Amounts are always positive; direction carries the sign |
| **Category** | One of a fixed set. Each is of type `expense`, `income`, or `transfer` |
| **Categorisation method** | How a category was decided: by rule, by model, or by the user |
| **Merchant memory** | Learned associations from an exact transaction description to a category |
| **Confidence** | A model-reported score for its own classification, in `[0, 1]` |
| **Review queue** | Transactions whose categorisation is not trusted, awaiting the user |
| **Import job** | A unit of work tracking one statement import from acceptance to outcome |
| **Chat session** | A conversation identified by an opaque id, holding prior turns |

---

## 3. Business rules

These constrain every behaviour below. Where a rule and a behaviour appear to
conflict, the rule wins.

### BR-1 — Monetary amounts are Rand
Every amount the system presents is South African Rand, formatted `R1,234.56`.
No amount is ever presented in another currency or as a bare number.
*Traces: NFR-3.*

### BR-2 — No amount without retrieval
The system states a monetary amount only if it retrieved that amount from
stored data while answering the current question. Estimating, inferring,
carrying a figure from another period, or reusing a number from an earlier turn
in place of a fresh lookup are all prohibited.
*Traces: NFR-1.*

### BR-3 — Absent is not zero
A period with no statement and a period with no spending are distinct facts and
are reported differently. The system never presents an unimported period as
zero. When a question resolves to a period with no statement, the system says
so and names the periods it holds; it does not substitute figures from another
period.
*Traces: NFR-2, D-1.*

### BR-4 — Learning requires confirmation
Only a categorisation trusted at the time it was made is written to merchant
memory. An untrusted classification is never recorded as knowledge, so it
cannot influence future transactions.
*Traces: FR-10.*

### BR-5 — Deterministic categorisation
Given identical input and identical stored state, categorisation produces an
identical result — on any machine, on any run. Where several rules match one
description, the winner is decided by explicit precedence, never by storage or
iteration order.
*Traces: FR-12.*

### BR-6 — Periods come from the data
A statement's period is determined from its transaction dates. The current date
never determines which period a statement belongs to.
*Traces: FR-4.*

### BR-7 — Import is all or nothing
An import either records a statement with all its transactions and an updated
summary, or records nothing.
*Traces: NFR-8.*

### BR-8 — Bounded cost
Each user action costs a bounded number of model requests: import is
independent of transaction count beyond its classification needs, and a
question is bounded by a fixed maximum of tool rounds. Conversation context is
bounded so per-question cost does not grow without limit.
*Traces: NFR-9, NFR-10.*

### BR-9 — Untrusted values never compose queries
Values originating from a statement, from the model, or from the user are
carried as parameters, never assembled into query text. Transaction
descriptions are model output derived from an uploaded file and are treated as
untrusted accordingly.
*Traces: NFR-12.*

---

## 4. Behaviour: statement import

### 4.1 Accepting a statement

**Input:** a file, supplied by the user.

**Validation, in order, before any work begins:**

| Condition | Result |
|---|---|
| Extension is not `.pdf`, `.png`, `.jpg`, `.jpeg` | Rejected: unsupported type |
| File is empty | Rejected: empty file |
| Otherwise | Accepted |

**Output on acceptance:** an import job identifier and the state `processing`,
returned immediately. Acceptance is not a claim that the import will succeed.

**Observable property:** the system remains responsive to all other requests
while an import runs. Acceptance completes in well under a second regardless of
statement size.
*Traces: FR-1, FR-6.*

### 4.2 Extraction

Every page of the statement is read, up to a configured maximum. Reading only
the first page is a defect: statements routinely run to several pages, and the
loss would be silent.

For each transaction the system captures: date, description, amount (always
positive), direction, service fee (zero when absent), and running balance.

If no transactions can be extracted, the import fails with reason `parse`.
*Traces: FR-2, FR-3.*

### 4.3 Determining the period

The statement's period is the **most frequent** (month, year) among its
transaction dates.

The mode is required rather than the first date because statements commonly
span a month boundary — a statement running 27 January to 27 February belongs
to February, and taking the first row would file the entire statement under
January.

Dates are accepted in the requested format and in ISO form; the model does not
reliably produce only one. Unparseable dates are ignored for this purpose. If
no date parses, the import fails with reason `parse`.
*Traces: FR-4, BR-6.*

### 4.4 Duplicate rejection

If a statement already exists for the determined period, the import fails with
reason `duplicate` and nothing is written. Re-submitting a statement is
therefore safe, which makes retrying a failed import safe.
*Traces: FR-5.*

### 4.5 Persistence

On success the system records the statement, every transaction with its
category, and a rebuilt summary for the period — as one unit. On any failure,
none of it.
*Traces: BR-7, NFR-8.*

### 4.6 Job lifecycle

```
          ┌──────────────┐
  accept  │  processing  │
 ────────►└──────┬───────┘
                 │
      ┌──────────┴──────────┐
      ▼                     ▼
 ┌─────────┐         ┌─────────────┐
 │  done   │         │   failed    │
 │ result  │         │ reason +    │
 │ summary │         │ error code  │
 └─────────┘         └─────────────┘
```

A finished job reports either a result (period and transaction count) or a
failure reason with one of these codes:

| Code | Meaning |
|---|---|
| `duplicate` | A statement for that period already exists |
| `parse` | No transactions, or no usable dates, could be extracted |
| `internal` | Anything else |

Job state is progress tracking, not history: it is retained only for recent
jobs and does not survive a restart. The durable record of an import is the
statement itself.

---

## 5. Behaviour: categorisation

### 5.1 Tiers

Every transaction is assigned exactly one category by the first tier that
matches:

| Tier | Basis | Model request | Trusted |
|---|---|---|---|
| 1 | Merchant memory — exact description seen before | no | yes |
| 2 | Keyword rule matching the description | no | yes |
| 3 | Direction is `CR` and nothing above matched → income | no | yes |
| 4 | Model classification | **yes** | only above threshold |

Cheaper, deterministic tiers must precede the model. This is a cost requirement
as much as a correctness one: most transactions must never reach tier 4.
*Traces: FR-7, FR-8, BR-8.*

### 5.2 Keyword matching

A keyword matches only on **whole-word** boundaries. Substring matching is a
defect: `FEE` would match `COFFEE`, and `UBER` would match `UBEREATS`.

Where several keywords match one description, the rule with the higher
precedence wins. Precedence is explicit and ordered from most specific to most
generic:

| Precedence | Kind | Examples |
|---|---|---|
| Highest | Specific services | `ELECTRICITY`, `WATER` |
| High | Brand names | `CHECKERS`, `TELKOM`, `TAKEALOT` |
| Low | Payment-type modifiers | `PREPAID`, `AIRTIME` |
| Lowest | Generic banking words | `FEE`, `CHARGE`, `BUNDLE` |

Ties at equal precedence are broken deterministically, so the outcome never
depends on storage order.

*Worked example:* `PREPAID ELECTRICITY TSHWANE` matches both `PREPAID`
(airtime) and `ELECTRICITY` (utilities). `ELECTRICITY` is more specific, so the
transaction is a utility.
*Traces: FR-12, BR-5.*

### 5.3 Within-import memory

If the same unseen description appears several times in one statement, it costs
**one** model request, not one per occurrence. The first classification is
available to the rest of the import.
*Traces: FR-9, BR-8.*

### 5.4 Trust and the review queue

A model classification is trusted if its confidence is at or above the
configured threshold, and untrusted below it.

| | Trusted | Untrusted |
|---|---|---|
| Category assigned | yes | yes |
| Appears in review queue | no | **yes** |
| Written to merchant memory | yes | **no** |

An untrusted classification is still shown to the user as a suggestion — it is
simply not treated as knowledge.
*Traces: FR-10, BR-4.*

### 5.5 Correction

The user may confirm a categorisation or replace it. Either action:

1. Marks the transaction trusted
2. Records the association in merchant memory, so the same description is
   categorised that way in future without a model request
3. Rebuilds the affected period's summary, since spending has moved between
   categories

*Traces: FR-11, FR-9.*

### 5.6 Rule changes

When categorisation rules or their precedence change, previously stored data
does not silently become correct — and merchant memory may hold associations
learned under the old rules. The system provides a means to re-apply current
rules to existing data.

Re-application affects only categorisations that rules produced. Decisions made
by the user or by the model are left alone: a rule change is not licence to
overwrite a human's judgement.
*Traces: BR-5.*

---

## 6. Behaviour: questions and answers

### 6.1 Routing

Every message is routed to exactly one of four outcomes:

| # | Message kind | Behaviour | Model requests |
|---|---|---|---|
| 1 | Greeting, or "what can you do?" | Answer directly: state what the system answers, name the available periods, give an example | 1 |
| 2 | Answerable from a defined query | Select query, execute, answer from the result | 2 |
| 3 | About the user's financial data, but no defined query fits | Generate a database query (§6.5) | 3 |
| 4 | Anything else | Decline in one sentence, name something it can answer | 1 |

Routing matters for cost, not just manners. Sending an out-of-scope question
down route 3 costs three requests to produce a refusal — and generates a
database query that cannot answer it.
*Traces: FR-13, FR-18, FR-19, FR-20, BR-8.*

### 6.2 Resolving periods

| Phrasing | Resolves to |
|---|---|
| A named month — "in March", "February 2026" | That month |
| A relative expression — "this month", "last month" | Computed from **today's real date** |
| No period mentioned | The period the user is currently viewing |

Every answer names the period it used. This is not a stylistic preference: it
is the only way the user can tell whether the question was understood.

The month being displayed never redefines "this month". If today is August and
the dashboard shows March, "this month" means August.
*Traces: FR-16, FR-17.*

### 6.3 Absent periods

When the resolved period has no statement, the system:

1. States that no statement exists for that period
2. Names the periods it does hold
3. States **no amount** for the absent period

It does not substitute another period's figures.
*Traces: BR-3, D-1, AC-11.*

### 6.4 Grounding

Every amount in an answer is a value retrieved while answering that question.

If the system offers figures for a period other than the one asked about, it
retrieves them first. Reusing a number seen earlier in the conversation in
place of a fresh lookup is prohibited, because a figure can be correct-looking
and wrong — a breakdown that sums to the right total can still be composed of
invented parts.
*Traces: FR-14, BR-2, NFR-1.*

### 6.5 Generated queries

Where a question concerns the user's financial data but no defined query fits,
the system may generate one, subject to all of:

| Rule | Rationale |
|---|---|
| Read-only | The query is model-generated and therefore untrusted |
| Must read at least one table | A query reading no table cannot answer anything about the user's finances |
| Result size bounded | An unbounded result would flood the context |
| Must use real category names | Inventing a category silently returns nothing |

A query failing any rule is refused and not executed. The user is told the
question could not be answered safely.
*Traces: FR-20, NFR-13.*

### 6.6 Conversation memory

Within a session, a question may depend on earlier turns — "and the month
before?" refers to the previously discussed subject and period.

Memory is bounded: past a configured number of turns a session restarts, after
which earlier turns no longer inform answers. Memory does not survive a service
restart. Memory is per session; sessions never see each other's history.

Durable knowledge lives in the database, not in conversation. A stored
conversation would preserve conclusions that later corrections invalidate.
*Traces: FR-15, NFR-10.*

### 6.7 Scope of advice

The system reports and explains the user's own recorded spending. Observations
grounded in that data are in scope, including where money went and how periods
compare.

Investment, tax, and legal advice are out of scope and are declined.
*Traces: FR-19, `requirements.md` §9.*

---

## 7. Behaviour: presentation

For a selected period the dashboard shows total spending, the largest spending
category, bank fees, and income; spending by category; and total spending
across recent periods.

On opening, the most recently imported period is selected. Opening on the
current calendar month would usually show an empty dashboard.

The user may switch between imported periods, and may review and correct
flagged categorisations (§5.5).

All figures shown are Rand-formatted (BR-1). Category colours are consistent
across every view, so a category is visually identifiable without reading the
legend.
*Traces: FR-21, FR-22, FR-23, FR-24.*

---

## 8. Interface contract

The dashboard reaches the agent service only through these operations. The
dashboard never reaches the database or the model.

| Operation | Input | Success | Failure |
|---|---|---|---|
| Health check | — | service is up | — |
| Submit statement | file | `202` job id + `processing` | `422` unsupported type or empty |
| Poll job | job id | job state, result or failure | `404` unknown or expired |
| List statements | — | imported periods, newest first | — |
| List categories | — | categories with type and colour | — |
| Period summary | period | per-category totals, counts, averages | — |
| Period income | period | total income and count | — |
| Bank fees | year | per-month fee totals | — |
| Trend | count of periods | per-period summaries, oldest first | — |
| Review queue | — | untrusted categorisations | — |
| Confirm categorisation | transaction | confirmed | `404` unknown transaction |
| Change category | transaction, category | updated, summary rebuilt | `404` unknown transaction |
| Ask a question | session id, message, viewed period | answer | `502` with a stated cause |
| Clear conversation | session id | cleared | — |

Money in results carries both a numeric value and a Rand-formatted string. The
numeric form exists for charts. **Only the formatted form is shown to the
model** — given a bare number, a model renders it in the wrong currency.
*Traces: BR-1, NFR-3, NFR-11.*

---

## 9. Error behaviour

### 9.1 Model failures

| Failure | Retried | Reported as |
|---|---|---|
| Capacity / temporarily unavailable | yes, with backoff | nothing, if a retry succeeds |
| Rate limit, short window | yes, honouring any stated delay | nothing, if a retry succeeds |
| Quota exhausted for the day | **no** | quota exhausted, naming the limit and model |
| Model unavailable to this account | **no** | model unavailable, naming the model |
| Network interruption | yes | nothing, if a retry succeeds |

Retrying a daily quota failure cannot succeed and wastes the remaining budget,
so it fails immediately.

Every failure reaching the user is one plain sentence naming the cause. A stack
trace is never shown.
*Traces: NFR-4, NFR-5, NFR-6.*

### 9.2 Infrastructure failures

If the database is unreachable at startup, the service **refuses to start** and
logs the host, port, and database. Starting successfully and failing every
request would present a missing dependency as an application defect.
*Traces: NFR-7.*

### 9.3 User-facing failures

An import failure states which of the three reasons applied (§4.6). A question
that cannot be answered safely says so rather than guessing.

---

## 10. Observable behaviour

At default verbosity the system records, for each question: the question, each
query executed with its arguments and row count, the time taken, and which
route (§6.1) was taken.

Default-verbosity records contain **no transaction descriptions and no
amounts**, so they can be shared when reporting a problem. Full payloads are
available at increased verbosity.

A question falling to a generated query (route 3) is recorded as a warning: a
recurring warning indicates a missing defined query, and adding one is
preferable to improving query generation.
*Traces: NFR-14.*

### 10.1 Model request tracing

Separately from logs, the system records every model request as a trace
capturing: which model was used, how long it took, how many tokens were
consumed, whether it succeeded, and how many retries were needed.

One user action produces **one** trace. A chat question appears as a single
trace with its model requests nested beneath it, so the cost of answering that
question is attributable to it rather than spread across unrelated log lines.

This makes bounded cost (BR-8) and the free-tier budget (NFR-9) observable
rather than inferred. Neither could previously be measured: quota exhaustion
was discovered by hitting it.

**Tracing is not on the critical path.** If the trace destination is
unreachable, misconfigured, or disabled, import, categorisation, and answering
all continue unaffected. An observability failure must never become an
application failure.

**Financial detail is redacted before anything is transmitted.** Prompts and
results carry transaction descriptions and monetary amounts. Before a trace
leaves the process:

| Removed | Retained |
|---|---|
| Monetary amounts, in any format | Token counts, latency, model names |
| Transaction descriptions and merchant names | Which query ran, and its period and category arguments |
| Statement contents | Trace structure, retry counts, success or failure |

What remains is exactly what bounded cost (BR-8) and the budget (NFR-9)
require. Measuring cost never needed the financial detail.

Redaction **fails closed**: if it cannot be applied to a value, that value is
removed rather than sent.

**Tracing is off unless explicitly configured.** No data is transmitted by
default, so the system cannot begin exporting because someone forgot to opt out.
*Traces: NFR-18, NFR-19, NFR-20, NFR-21.*

---

## 11. Edge cases

| Situation | Required behaviour |
|---|---|
| Statement spans two months | Filed under the month holding most transactions (§4.3) |
| Statement has more pages than the maximum | Pages up to the maximum are read; the truncation is recorded |
| Same merchant appears N times, unseen | One model request, not N (§5.3) |
| Description matches two keyword rules | More specific rule wins, deterministically (§5.2) |
| A credit from an unrecognised source | Treated as income (tier 3) |
| A refund from a known merchant | Categorised to that merchant's category, not income — tier 2 precedes tier 3 |
| Question about an unimported period | Absence reported, no amount stated (§6.3) |
| Relative period while viewing an older one | Resolved against today, not the view (§6.2) |
| Conversation exceeds the turn limit | Session restarts; earlier turns no longer inform answers |
| No statements imported at all | Dashboard shows empty state; the agent says it has no periods |
| Model returns a category that does not exist | Falls back to the catch-all category |
| Model returns malformed output | Treated as a classification failure; the transaction is flagged untrusted |

---

## 12. Acceptance criteria and verification

Each criterion from `requirements.md` §11, with its current verification status.

| ID | Criterion | Verified by |
|---|---|---|
| AC-01 | All pages of a multi-page statement are extracted | manual only — see Known gaps |
| AC-02 | Month-spanning statement filed under the modal month | `test_service.py` |
| AC-03 | Duplicate period rejected, nothing written | manual only — see Known gaps |
| AC-04 | Upload returns immediately; service stays responsive | manual only — see Known gaps |
| AC-05 | Failed import leaves no partial data | manual only — see Known gaps |
| AC-06 | Keyword match costs no model request | `test_categorizer.py` |
| AC-07 | Rule conflict resolves to the specific rule, repeatably | `test_categorizer.py` |
| AC-08 | Repeated unseen description costs one model request | `test_categorizer.py` |
| AC-09 | Untrusted classification queued, not learned | `test_categorizer.py` |
| AC-10 | Correction is remembered | partial — see Known gaps |
| AC-11 | Absent period reported without an amount | `test_queries.py`, `test_tools.py` |
| AC-12 | Every stated amount was retrieved | `test_prompts.py` (rule only) — see Known gaps |
| AC-13 | Every stated amount is Rand | `test_tools.py`, `test_queries.py`, `test_nl_query.py` |
| AC-14 | "This month" is the real current month | `test_prompts.py` (rule only) — see Known gaps |
| AC-15 | Follow-up questions resolve against earlier turns | manual only — see Known gaps |
| AC-16 | Greeting costs no database query | `test_prompts.py` (rule only) — see Known gaps |
| AC-17 | Out-of-scope question generates no query | `test_prompts.py` (rule only) — see Known gaps |
| AC-18 | Unsafe generated query refused | `test_nl_query.py` |
| AC-19 | Transient failure retried invisibly | `test_llm.py` |
| AC-20 | Daily quota fails immediately, cause stated | `test_llm.py` |
| AC-21 | Service refuses to start without a database | manual only — see Known gaps |
| AC-22 | Dashboard cannot reach database or model | structural — see Known gaps |
| AC-23 | Suite passes with no `.env`, database, or key | verified manually |
| AC-24 | Every model request is traced with model, latency, tokens, outcome | implemented — see Known gaps |
| AC-25 | One user action is one trace, model requests nested | implemented — see Known gaps |
| AC-26 | Tracing unavailable does not break the system | `test_tracing.py` |
| AC-27 | No description or amount appears in transmitted trace data | `test_tracing.py` |
| AC-28 | Tracing is off unless configured | `test_tracing.py` |

---

## 13. Known verification gaps

Stated plainly rather than implied by omission.

1. **Model-dependent criteria are only partially verifiable.** AC-12, AC-14,
   AC-16 and AC-17 depend on model behaviour. Tests confirm the governing rule
   is present in the instructions, not that the model obeys it. Closing this
   properly needs recorded model interactions or an evaluation suite.
2. **Import path has no automated end-to-end test.** AC-01, AC-03, AC-04 and
   AC-05 have been verified by hand but not automatically.
3. **AC-10 is partially covered.** Merchant memory is tested; the correction
   endpoint writing to it is not.
4. **AC-22 is structural.** It holds because the dashboard has neither the
   credentials nor the client libraries, but nothing asserts it.

5. **Tracing is specified but not built.** AC-24 to AC-27 describe behaviour
   agreed under Change Control and scheduled in `tasks.md` Phase 5. They are
   listed here so the specification is not read as describing something that
   exists.

These gaps are not a request for changes. They record what "verified" currently
means, so the word is not overclaimed.

---

## 14. Requirements verified outside runtime behaviour

Three requirements constrain the repository and its verification rather than
the running system, so they have no behaviour in §4–§10:

| Requirement | Constraint | Where it holds |
|---|---|---|
| NFR-15 | Real financial data is never committed | Version-control configuration excludes statement files; only synthetic samples are committed |
| NFR-16 | The suite runs with no database, key, or network | AC-23 |
| NFR-17 | Tests never call the model | Every model call site is substituted during testing |

They are recorded here so no requirement is silently dropped.

## 15. Traceability

- `requirements.md` — why the system exists, what it must achieve
- `SPEC.md` (this document) — what it must do, verifiably
- Contributor conventions — how this repository is worked in

Every behaviour above cites the requirement it serves. Every requirement in
`requirements.md` §4 and §5 appears in at least one behaviour or rule here.
