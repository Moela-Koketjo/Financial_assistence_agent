# Finance Agent — Tasks

Status: **approved — not started**
Amended: Phase 5 added under Change Control
Traces to: `plan.md`

Concrete units of work from `plan.md`. Each is small enough to implement in one
pass, states what it verifies, and is traceable to acceptance criteria in
`SPEC.md` §12.

**No task here is required for the system to work.** Each closes a stated
verification gap or settles an open decision.

---

## Phase 1 — Import verification

### TASK-001 — End-to-end import test harness

**Verifies:** groundwork for AC-01, AC-03, AC-04, AC-05

Build the fixture that drives the API in-process with extraction substituted,
so an import can run end to end without contacting the model.

- Test-only HTTP client against the app
- Extraction substituted with a deterministic transaction set
- Database fixture reused from the existing suite

**Expected changes:** test fixtures only.
**Tests:** one smoke test proving an import completes and a job reports `done`.
**Depends on:** nothing.
**Constraint:** must not call the model; must not require MySQL.

### TASK-002 — All pages are extracted

**Verifies:** AC-01

Assert that a multi-page statement yields transactions from every page, and
that a statement exceeding the page maximum is truncated at the maximum with
the truncation recorded.

**Expected changes:** tests only.
**Tests:** three-page statement yields all rows; over-limit statement truncates
and records it.
**Depends on:** TASK-001.

### TASK-003 — Duplicate period is rejected

**Verifies:** AC-03

Assert that importing a period twice fails with reason `duplicate`, and that
the second attempt writes nothing — statement count, transaction count, and
summary all unchanged.

**Expected changes:** tests only.
**Tests:** duplicate rejected; no data written; original import intact.
**Depends on:** TASK-001.

### TASK-004 — Failed import leaves nothing

**Verifies:** AC-05

Assert that a failure during categorisation or persistence leaves no statement,
no transactions, and no summary rows.

**Expected changes:** tests only.
**Tests:** induced failure mid-import; database unchanged afterwards.
**Depends on:** TASK-001.
**Note:** exercises BR-7. If it fails, that is a real defect — Change Control.

### TASK-005 — Acceptance does not block

**Verifies:** AC-04

Assert that submitting a statement returns promptly and that other operations
remain answerable while the import runs.

**Expected changes:** tests only.
**Tests:** submission returns within a small bound; a second request succeeds
during the import.
**Depends on:** TASK-001.

### TASK-006 — Correction teaches merchant memory

**Verifies:** AC-10

Assert that changing a transaction's category records the association, marks
the transaction trusted, rebuilds the period summary, and that the same
description is subsequently categorised from memory without a model call.

**Expected changes:** tests only.
**Tests:** correction writes memory; summary reflects the move; next occurrence
uses memory.
**Depends on:** TASK-001.

---

## Phase 2 — Structural guarantees

### TASK-007 — Startup refuses an unreachable database

**Verifies:** AC-21

Assert that startup fails when the database is unreachable, and that the
failure names host, port, and database. Assert startup succeeds when reachable.

**Expected changes:** tests only.
**Tests:** unreachable database aborts startup with a named cause; reachable
database starts.
**Depends on:** nothing.

### TASK-008 — The dashboard cannot reach data or model

**Verifies:** AC-22

Assert the credential boundary structurally: the dashboard declares no database
or model dependency, and no dashboard module imports across the service
boundary.

**Expected changes:** tests only, in the dashboard service.
**Tests:** declared dependencies contain no database or model client; no
cross-boundary import exists.
**Depends on:** nothing.
**Note:** the dashboard currently has no test suite; this task establishes one.

---

## Phase 3 — Model evaluation

### TASK-009 — Evaluation harness

**Verifies:** groundwork for AC-12, AC-14, AC-16, AC-17

Build a suite that runs fixed questions against the agent and asserts
observable properties — which periods were queried, whether any query ran,
whether stated amounts appear in retrieved results.

- Excluded from the default test run
- Each case records the behaviour it guards
- Asserts properties, never exact wording

**Expected changes:** new evaluation suite; test configuration to exclude it.
**Tests:** harness runs and reports per-case pass or fail.
**Depends on:** nothing.
**Constraint:** must not run in the default suite (NFR-16, NFR-17).

### TASK-010 — Relative periods resolve against today

**Verifies:** AC-14

Cases asserting that "this month" and "last month" query the period computed
from the real current date, regardless of the period being viewed.

**Expected changes:** evaluation cases only.
**Tests:** relative expressions query the expected period while a different
period is displayed.
**Depends on:** TASK-009.

### TASK-011 — Stated amounts were retrieved

**Verifies:** AC-12

Cases asserting that every monetary amount in an answer appears in the results
retrieved during that exchange. Includes the case that produced the original
failure: a question about a period with no statement, where an answer offering
another period's figures must have queried that period first.

**Expected changes:** evaluation cases only.
**Tests:** amounts in the answer are a subset of amounts retrieved; absent
period states no amount.
**Depends on:** TASK-009.
**Note:** guards BR-2, the highest-severity rule in the specification.

### TASK-012 — Routing costs what it should

**Verifies:** AC-16, AC-17

Cases asserting that a greeting runs no query, that an out-of-scope question
runs no query and generates none, and that each is answered in a single model
request.

**Expected changes:** evaluation cases only.
**Tests:** greeting and out-of-scope questions execute no query; request count
is one.
**Depends on:** TASK-009.

### TASK-013 — Follow-up questions use conversation context

**Verifies:** AC-15

Cases asserting that a question depending on an earlier turn is resolved using
that turn — a follow-up naming no subject queries the previously discussed
subject, and a follow-up naming no period queries the previously discussed
period.

Includes the boundary: past the turn limit the session restarts and earlier
turns no longer inform answers.

**Expected changes:** evaluation cases only.
**Tests:** follow-up queries the prior subject; follow-up queries the prior
period; context is not carried across a session restart.
**Depends on:** TASK-009.

---

## Phase 4 — Open decisions

### TASK-014 — Decide review-queue prompting

**Verifies:** resolves `requirements.md` open question 1

Decide whether the system surfaces a prompt when the review queue grows, or
whether silence is accepted. Record the outcome as a decision.

**Expected changes:** `requirements.md` and `SPEC.md` if behaviour is added;
documentation only if not.
**Tests:** only if behaviour is added.
**Depends on:** your decision.
**Note:** Change Control — specification is amended before any code.

### TASK-015 — Decide statement deletion

**Verifies:** resolves `requirements.md` open question 3

Confirm deletion remains out of scope, or bring it into scope. If in scope, it
needs its own specification first: what happens to transactions, merchant
memory learned from them, and summaries.

**Expected changes:** `requirements.md` and `SPEC.md` first; code only after.
**Tests:** only if brought into scope.
**Depends on:** your decision.
**Note:** introduces the system's first destructive operation. Specify before
building.

---

## Phase 5 — Tracing

Added under Change Control after `requirements.md` and `SPEC.md` were amended.
Unlike Phases 1–4 this adds capability, not verification.

**Blocked:** the package index was unreachable when these were written, so the
SDK shape is unverified. TASK-016 confirms it before anything depends on it.

### TASK-016 — Confirm the tracing SDK and self-hosted deployment

**Verifies:** groundwork for AC-24 to AC-27

Establish the facts the remaining tasks assume: SDK package and version, its
Python requirement, the services a self-hosted deployment needs, and whether
trace delivery is asynchronous by default.

**Expected changes:** dependency added to the agent service only.
**Tests:** the suite still passes with the dependency present and tracing off.
**Depends on:** a reachable package index.
**Note:** if self-hosting proves disproportionate for this stack, that is a
conflict with NFR-20 — Change Control, not a quiet switch to the hosted option.

### TASK-017 — Trace model requests at the gateway

**Verifies:** AC-24

Instrument the single function every model call passes through, recording
model, latency, token usage, outcome, and retry count. Retries belong to the
request that caused them, not to separate events.

**Expected changes:** model gateway; settings for tracing configuration.
**Tests:** a traced call records the expected fields; retries appear within one
record; the suite passes with tracing disabled.
**Depends on:** TASK-016.
**Constraint:** tests must not call the model or require a trace destination.

### TASK-018 — Trace a user action as one trace

**Verifies:** AC-25

Open a trace at the request boundary so one chat question is one trace with its
model requests nested beneath it, rather than unrelated records.

**Expected changes:** request handling; tool-call loop.
**Tests:** a question producing two model requests yields one trace containing
both.
**Depends on:** TASK-017.

### TASK-019 — Tracing failures never reach the user

**Verifies:** AC-26

Assert that an unreachable, misconfigured, or disabled trace destination leaves
import, categorisation, and answering unaffected.

**Expected changes:** error handling in the tracing component.
**Tests:** unreachable destination — question still answered; tracing disabled
— system starts and answers normally; malformed configuration does not prevent
startup.
**Depends on:** TASK-017.
**Note:** guards the rule that observability must not become an application
failure. If a tracing fault can surface to the user, that is a defect.

### TASK-020 — Redact financial detail before transmission ✅ done

**Verifies:** AC-27, AC-28

Superseded by Change Control: self-hosting Langfuse v3+ requires roughly six
services, which is disproportionate here. NFR-20 was amended to permit an
external collector provided financial detail is removed before it leaves the
process. Redaction is implemented in `agent/tracing.py` and wired into the
client as its mask; 21 tests assert it cannot be defeated.

**Original scope, retained for the record:** self-host the trace store.

**Verified:** AC-27

Add the trace store to the compose stack with its own persistence, configured
so no trace data leaves the deployment. The agent receives its configuration as
optional overrides; absent configuration means tracing off.

**Expected changes:** compose file; agent environment; README.
**Tests:** stack starts with tracing enabled and traces are recorded; stack
starts with tracing absent and behaves identically.
**Depends on:** TASK-016.
**Note:** adds a container with its own database. If that proves
disproportionate, raise it rather than silently falling back to hosted.

---

## Order and traceability

| Task | Verifies | Depends on |
|---|---|---|
| TASK-001 | harness | — |
| TASK-002 | AC-01 | 001 |
| TASK-003 | AC-03 | 001 |
| TASK-004 | AC-05 | 001 |
| TASK-005 | AC-04 | 001 |
| TASK-006 | AC-10 | 001 |
| TASK-007 | AC-21 | — |
| TASK-008 | AC-22 | — |
| TASK-009 | harness | — |
| TASK-010 | AC-14 | 009 |
| TASK-011 | AC-12 | 009 |
| TASK-012 | AC-16, AC-17 | 009 |
| TASK-013 | AC-15 | 009 |
| TASK-014 | decision | — |
| TASK-015 | decision | — |
| TASK-016 | groundwork | reachable index |
| TASK-017 | AC-24 | 016 |
| TASK-018 | AC-25 | 017 |
| TASK-019 | AC-26 | 017 |
| TASK-020 | AC-27 | 016 |

On completion of TASK-001 through TASK-013, every acceptance criterion in
SPEC §12 is automatically verified, and SPEC §13 can be reduced to whatever
genuinely remains.

## Standing rules

1. Implement one task at a time. Do not fold later tasks into an earlier one.
2. A test that fails because the system is wrong is a **defect**. Report it,
   agree the fix, then fix it. Never adjust a test so a defect passes.
3. No task may make the default test run require a database, an API key, or
   network access.
4. Any change to requirements or specification goes through Change Control
   before code.
