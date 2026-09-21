# Finance Agent — Implementation Plan

Status: **approved**
Traces to: `SPEC.md` §13, `requirements.md` open questions

---

## What this plan covers

The system implements the approved specification. This plan therefore does not
sequence building it — that work is done. It sequences the **outstanding work**:
closing the gap between what the specification requires and what is
automatically verified, plus the decisions `requirements.md` leaves open.

Everything here is optional. The system is usable and correct as it stands; the
plan exists so the remaining work is explicit rather than remembered.

## Current position

| | State |
|---|---|
| Acceptance criteria | 23 defined |
| Verified by automated test | 11 |
| Verified by hand only | 7 |
| Rule-present only (model-dependent) | 4 |
| Structural, unasserted | 1 |
| Test suite | 71 tests, no database, key, or network required |

The gap is concentrated in two places: **the import path has no end-to-end
test**, and **model-dependent behaviour cannot be verified by asserting that an
instruction exists**.

---

## Phase 1 — Close the import verification gap

**Why first.** It is the largest block of unverified criteria (AC-01, AC-03,
AC-04, AC-05, AC-10), it needs no new infrastructure, and it is the path where
a regression would be most damaging — a silently wrong import corrupts stored
data, and every later answer inherits the error.

**Approach.** Drive the API in-process with a substituted extraction step, so a
synthetic statement can be imported end to end without calling the model. The
synthetic generator already produces deterministic statements, which makes
expected results exact rather than approximate.

**Verifies:** AC-01, AC-03, AC-04, AC-05, AC-10.

**Depends on:** nothing.

**Risk:** low. Tests only; no production code changes expected. If an assertion
fails, that is a genuine defect and goes through Change Control rather than
being asserted around.

## Phase 2 — Assert the structural guarantees

**Why second.** Cheap, and it converts a claim into a check. AC-22 (the
dashboard cannot reach the database or the model) currently holds because of
what the dashboard does *not* depend on — which is exactly the kind of property
that erodes silently when someone adds an import.

**Approach.** Assert that the dashboard declares no database or model
dependency and imports nothing across the service boundary. Assert the startup
database check refuses to start on an unreachable database (AC-21).

**Verifies:** AC-21, AC-22.

**Depends on:** nothing.

**Risk:** low.

## Phase 3 — Evaluate model-dependent behaviour

**Why third.** It is the largest piece of work and the only one needing new
infrastructure, so it should follow the cheap wins. It is also the most
valuable: four acceptance criteria (AC-12, AC-14, AC-16, AC-17) currently rest
on instructions being present rather than obeyed, and each corresponds to a
failure that has occurred.

**Approach.** A small evaluation suite: fixed inputs, recorded expectations,
run on demand rather than in the normal test run. Each case asserts an
observable property rather than exact wording — which period was queried,
whether any query ran, whether a stated amount appears in retrieved results.

Recorded model interactions would let the suite run offline; live runs would
measure current behaviour. The two are complementary and the choice can be
deferred until Phase 3 begins.

**Verifies:** AC-12, AC-14, AC-16, AC-17 — properly rather than by proxy.

**Depends on:** nothing technically, but best attempted when daily quota is not
already committed to other work.

**Risk:** medium. Evaluation suites are easy to write so loosely they pass
regardless, or so tightly they fail on harmless rewording. Asserting observable
properties rather than text is the mitigation.

## Phase 4 — Resolve the open decisions

**Why last.** These are product decisions, not verification. Each may result in
no work at all.

| Open question | Possible outcomes |
|---|---|
| Review queue is load-bearing but unprompted | Surface a prompt when it grows; or accept silence and record the decision |
| Statement deletion is out of scope | Confirm and close; or bring into scope, which changes `requirements.md` and `SPEC.md` first |

**Depends on:** your decisions. Any change here amends `requirements.md` and
`SPEC.md` **before** code, via Change Control.

**Risk:** deletion is the higher-risk item — it introduces a destructive
operation to a system that currently has none, and would need its own
specification for what happens to derived data.

---

## Sequence and dependencies

```
Phase 1  import end-to-end tests        ──┐
Phase 2  structural assertions          ──┼──► independent, any order
Phase 3  model evaluation suite         ──┘
Phase 4  open decisions                 ──► may amend requirements/spec first
```

Phases 1–3 are independent; the order given reflects value per unit of effort,
not technical dependency. Phase 4 is gated on decisions, not code.

## Testing requirements per phase

| Phase | Added | Constraint |
|---|---|---|
| 1 | End-to-end import tests with substituted extraction | Must not call the model |
| 2 | Structural and startup assertions | Must not require a database |
| 3 | Evaluation suite, run on demand | Must be excluded from the default run |
| 4 | Depends on the decision | Spec amended before code |

The standing constraint holds throughout: **the default test run requires no
database, no API key, and no network** (NFR-16, NFR-17). Phase 3 introduces the
first tests that may contact the model, and they must therefore sit outside the
default run.

## Risks

| Risk | Mitigation |
|---|---|
| A new test reveals a real defect | Change Control: report, agree, then fix. Do not adjust the test to pass |
| Evaluation suite is too loose to catch regressions | Assert observable properties, not wording |
| Phase 3 consumes daily quota | Run on demand, not in the default suite |
| Phase 4 expands scope | Amend `requirements.md` and `SPEC.md` before any code |

## Definition of done

- Every acceptance criterion is either automatically verified, or listed in
  SPEC §13 with a stated reason
- No criterion claims verification it does not have
- The default test run still needs no database, key, or network
