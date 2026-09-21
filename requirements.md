# Finance Agent — Requirements

Status: **approved**

This document states *why the system exists and what it must achieve*. It does
not describe behaviour in detail (see `SPEC.md`) or implementation (see
the repository's contributor conventions).

---

## 1. Problem statement

A person with a South African bank account receives monthly statements as PDFs.
Those statements are accurate but inert: they list transactions without telling
you what you spend money on, whether that is changing, or where it goes.

Answering even simple questions — *"what do I spend most on?"*, *"is grocery
spending going up?"* — means manually transcribing and categorising dozens of
rows per month. The effort is high enough that most people never do it, so the
information sits unused in a PDF.

The system turns statements into categorised, queryable data and lets the user
ask questions of it in plain English, instead of building spreadsheets.

## 2. Goals

- **G1** — Extract transactions from a bank statement without manual typing.
- **G2** — Categorise transactions automatically, and improve with correction.
- **G3** — Answer natural-language questions about spending using real stored
  data, never estimates.
- **G4** — Present spending visually for a chosen month and across months.
- **G5** — Remain usable on a free-tier LLM account with a small daily request
  budget.
- **G6** — Never present fabricated, missing, or wrongly-denominated financial
  figures as fact.

## 3. Users and actors

| Actor | Description | Interactions |
|---|---|---|
| **Account holder** | Single, non-technical user. The only human actor. | Uploads statements, reads charts, asks questions, corrects categorisations |
| **Dashboard service** | Streamlit thin client. Sole consumer of the API. | HTTP requests to the agent service |
| **Agent service** | FastAPI backend owning all data and LLM access | Parses, categorises, persists, answers |
| **Gemini API** | External LLM. Untrusted, rate-limited, intermittently unavailable. | Vision extraction, classification, tool selection, phrasing |
| **MySQL** | System of record | Stores statements, transactions, categories, merchant memory |

There is no authentication and no multi-user support. The system assumes one
user; this is a deliberate simplification, not an oversight.

## 4. Functional requirements

### Statement import

- **FR-1** The system shall accept a bank statement as PDF, PNG, JPG, or JPEG.
- **FR-2** The system shall extract every transaction from **all** pages of a
  statement, up to a configured page limit — not only the first page.
- **FR-3** For each transaction the system shall capture: date, description,
  amount, direction (money in or out), service fee, and running balance.
- **FR-4** The system shall determine which calendar month a statement belongs
  to from the transaction dates themselves, never from the current date.
- **FR-5** The system shall reject a statement for a month already imported,
  rather than creating duplicate records.
- **FR-6** Import shall not block other requests; the user shall be able to see
  progress and the final outcome.

### Categorisation

- **FR-7** Every transaction shall be assigned exactly one category.
- **FR-8** Categorisation shall attempt cheaper, deterministic methods before
  invoking the LLM.
- **FR-9** The system shall remember categorisations for descriptions it has
  seen before, so the same merchant need not be classified twice.
- **FR-10** Only categorisations confirmed as reliable shall be remembered;
  low-confidence guesses shall not become durable knowledge.
- **FR-11** The user shall be able to review low-confidence categorisations and
  correct them, and a correction shall be remembered.
- **FR-12** When several categorisation rules match one transaction, the system
  shall resolve the conflict **deterministically** — the same statement must
  categorise identically on every machine and every run.

### Questions and answers

- **FR-13** The user shall be able to ask questions in natural English about
  their spending.
- **FR-14** Answers shall be derived from stored data, retrieved at the time of
  asking.
- **FR-15** The system shall answer follow-up questions that depend on earlier
  turns of the same conversation.
- **FR-16** The system shall resolve relative time expressions ("this month",
  "last month") against the real current date.
- **FR-17** Where a question names no period, the system shall use the period
  the user is currently viewing, and shall state which period it used.
- **FR-18** The system shall answer greetings and "what can you do" questions
  by orienting the user, without a database query.
- **FR-19** The system shall decline questions unrelated to the user's
  financial data, briefly, and redirect to what it can answer.
- **FR-20** Where no pre-defined query answers a question about the user's
  financial data, the system may generate a database query, subject to NFR-13.

### Presentation

- **FR-21** The system shall display, for a selected month: total spending, the
  largest category, bank fees, and income.
- **FR-22** The system shall display spending broken down by category, and
  total spending across recent months.
- **FR-23** The system shall open on the most recently imported statement
  rather than an empty month.
- **FR-24** The system shall list imported statements and allow switching
  between them.

## 5. Non-functional requirements

### Correctness and trust

- **NFR-1** The system shall never state a monetary amount it has not retrieved
  from stored data. Estimating, inferring, or carrying a figure over from
  another period is prohibited.
- **NFR-2** The system shall never report an absent period as zero spending. A
  period with no statement and a period with no spending are different facts
  and shall be reported differently.
- **NFR-3** All monetary amounts shall be presented in South African Rand and
  shall never be rendered in another currency.

*NFR-1 and NFR-2 are the highest-severity requirements in this document. A
finance tool that presents a plausible but fabricated figure is worse than one
that declines to answer: the user has no way to tell the two apart, and acts on
the number either way.*

### Reliability

- **NFR-4** Transient LLM failures (capacity errors, per-minute rate limits,
  network resets) shall be retried automatically.
- **NFR-5** Failures that retrying cannot resolve (exhausted daily quota,
  unavailable model) shall fail immediately rather than consuming attempts.
- **NFR-6** LLM and infrastructure failures shall be reported to the user in one
  plain sentence naming the cause — never a stack trace or a generic message.
- **NFR-7** The service shall refuse to start if its database is unreachable,
  rather than starting and failing every request.
- **NFR-8** A failed import shall leave no partial data.

### Cost

- **NFR-9** The system shall operate within a free-tier LLM budget of roughly
  20 requests per day per model. Import and question-answering shall each cost
  a small, bounded number of requests.
- **NFR-10** Conversation context shall be bounded, so cost per question does
  not grow without limit over a long conversation.

### Observability

- **NFR-18** The system shall record, for every model request, the model used,
  the latency, the token usage, and the outcome — so cost and performance are
  observable rather than inferred from logs.
- **NFR-19** The system shall present a single model request and a single user
  action as connected, so the cost of one question can be attributed to it.
- **NFR-20** Trace data may be sent to an external collector **only if
  financial detail is removed before it leaves the process**. Transaction
  descriptions and monetary amounts shall be redacted; structure, timing, token
  usage, model names, and which queries ran may be transmitted. Redaction shall
  fail closed: if it cannot be applied, nothing is sent.
- **NFR-21** Tracing shall be disabled unless explicitly configured, so no data
  is transmitted by default.

### Security and privacy

- **NFR-11** The dashboard shall hold no database credentials and no LLM
  credentials, and shall be unable to reach either directly.
- **NFR-12** Values originating from statements or user input shall never be
  interpolated into database queries.
- **NFR-13** Generated database queries shall be read-only and bounded.
- **NFR-14** Logs at default verbosity shall not contain transaction
  descriptions or amounts, so they are safe to share when reporting a problem.
- **NFR-15** Real financial data shall never be committed to version control.

### Maintainability

- **NFR-16** The test suite shall run with no database, no API key, and no
  network access.
- **NFR-17** Tests shall never call the LLM.

## 6. Constraints

- **C-1** The LLM is Google Gemini, accessed via the `google-genai` SDK.
- **C-2** The database is MySQL. (Tests use in-memory SQLite — the single
  documented exception.)
- **C-3** Two independently deployable services that share no code and
  communicate only over HTTP.
- **C-4** The LLM is stateless; conversation memory is the caller's
  responsibility.
- **C-5** Free-tier LLM quota is enforced per project **per model**.
- **C-6** Statements are FNB-format South African bank statements.
- **C-7** The repository's contributor conventions take precedence over this
  document on any matter of implementation style.

## 7. Assumptions

- **A-1** One user, one account. No authentication is required.
- **A-2** Statements are legible; parsing quality depends on the vision model.
- **A-3** The user reviews flagged categorisations; the review queue only
  improves accuracy if used.
- **A-4** Statement volume is low (order of one per month), so query
  performance is not a present concern.
- **A-5** The user's own machine or private host — the system is not exposed
  publicly.

## 8. Dependencies

| Dependency | Used for | Failure impact |
|---|---|---|
| Google Gemini API | Extraction, classification, chat | No import, no chat; charts still work |
| MySQL | All persistence | Service refuses to start (NFR-7) |
| Docker / Docker Compose | Packaging and orchestration | Local route still available |
| Langfuse | Model-request tracing, redacted | Tracing unavailable; the system continues to function |

## 9. Out of scope

- Multi-user support, authentication, authorisation
- Bank APIs or automatic statement fetching; import is manual
- Budgeting, forecasting, goals, or alerts
- Investment, tax, or financial advice of any kind
- Editing or deleting statements after import
- Currencies other than Rand; banks other than FNB
- Mobile applications
- Durable conversation history across restarts
- Transmitting unredacted financial detail to any external service (NFR-20)

## 10. Success criteria

- **SC-1** A statement can be imported and categorised without manual data entry.
- **SC-2** The majority of transactions are categorised without an LLM call, and
  that proportion improves as merchant memory grows.
- **SC-3** Common spending questions are answered correctly from stored data.
- **SC-4** A full import plus a normal session of questions fits within a
  free-tier daily budget.
- **SC-5** No answer ever contains an invented, missing, or wrongly-denominated
  figure.
- **SC-6** A newcomer can run the system with one command and verify the logic
  with one more.

## 11. Acceptance criteria

Verifiable statements. `SPEC.md` will bind each to concrete behaviour, and
tests to each criterion.

| ID | Criterion |
|---|---|
| **AC-01** | Importing a 3-page statement yields every transaction on all 3 pages |
| **AC-02** | A statement spanning two months is filed under the month holding most of its transactions |
| **AC-03** | Re-importing an already-imported month is rejected, and no duplicate data is written |
| **AC-04** | Upload returns immediately; other endpoints remain responsive while the import runs |
| **AC-05** | A failed import leaves no statement and no transactions |
| **AC-06** | A description matching a seeded keyword is categorised without an LLM call |
| **AC-07** | A description matching two rules resolves to the more specific one, identically on repeated runs |
| **AC-08** | The same unseen description appearing N times in one import costs exactly one LLM call |
| **AC-09** | A categorisation below the confidence threshold appears in the review queue and is not written to merchant memory |
| **AC-10** | Correcting a categorisation causes the same description to be categorised that way subsequently |
| **AC-11** | A question about a period with no statement reports that fact and states no amount for it |
| **AC-12** | Every amount in an answer is a figure retrieved during that exchange |
| **AC-13** | Every amount in an answer is expressed in Rand |
| **AC-14** | "This month" resolves to the real current month regardless of which month is displayed |
| **AC-15** | A follow-up question referring to an earlier subject is answered correctly |
| **AC-16** | A greeting is answered without a database query |
| **AC-17** | An unrelated question is declined without generating a database query |
| **AC-18** | A generated query that is not a bounded read-only query is refused |
| **AC-19** | A transient LLM failure is retried and succeeds without the user seeing an error |
| **AC-20** | An exhausted daily quota fails immediately and reports the cause in one sentence |
| **AC-21** | The service refuses to start when the database is unreachable, naming host and database |
| **AC-22** | The dashboard cannot reach the database or the LLM |
| **AC-23** | The full test suite passes with no `.env`, no database, and no API key |
| **AC-24** | Every model request appears as a trace recording model, latency, token usage, and outcome |
| **AC-25** | One user action appears as one trace, with its model requests nested beneath it |
| **AC-26** | Tracing being unavailable does not prevent import, categorisation, or answering |
| **AC-27** | No transaction description or monetary amount is present in transmitted trace data |
| **AC-28** | Tracing is off unless explicitly configured |

---

## Decisions

- **D-1 — Absent periods stop at the negative answer.** When a question resolves
  to a period with no statement, the system reports that absence and names the
  periods it does have. It does not substitute figures from another period.
  Rationale: the answer stays strictly about the period asked for, and the user
  chooses whether to look elsewhere. Binds AC-11.

## Open questions for review

1. **A-3 is load-bearing and untested.** Accuracy depends on the user working
   the review queue. Should the system nudge when the queue grows, or is
   silence acceptable?
2. **NFR-9's budget is per model, not per system.** Cost is stated per model
   because quota is enforced per model. Worth confirming that framing is what
   you want before `SPEC.md` builds on it.
3. **Statement deletion is out of scope.** A mis-imported statement therefore
   cannot be removed through the interface. Confirm that is intended.
