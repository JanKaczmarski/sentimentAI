# API And Storage Contract Decisions

**Status:** Accepted; remaining v0.2 items resolved by decision 0006

**Date:** 2026-08-16

## Purpose

This record captures decisions needed for `FEAT-006`, `FEAT-008`, and
`FEAT-009`. It supplements the API drafts in `Inżynierka docs.md` and
`ARCHITECTURE.md`; it does not approve implementation while material entries
remain open. Decision 0006 now fixes the remaining v0.2 request, response, and
persistence contract.

## Scope Boundary

This record approves the account identity, API-key, error, and Investment Thesis
schema direction needed to prepare account API work. It does not close
`FEAT-006`: the final corpus split, benchmark protocol, complete v0.2 API
schemas, and database contract remain open there. The current in-memory account
implementation is development preparation only; it is not the PostgreSQL
implementation required by `FEAT-008`, and full account/thesis CRUD remains in
`FEAT-009`.

## Confirmed Decisions

### Account identity

- The server generates an immutable UUID when it creates an account.
- Account creation requires an email address.
- Account creation requires a username.
- Email addresses are unique across accounts.
- Usernames are unique across accounts.
- A duplicate email is rejected with the message `email in use`.

### User selection for the non-production API

- Account-specific API operations receive an `api_key` query parameter.
- The API key identifies the account for the request in the absence of login
  or session authentication.
- The server must issue an API key when creating an account; otherwise a new
  account has no value to submit on later requests.
- Only a one-way digest of the API key may be stored. The raw key is returned
  only when the account is created and must not be logged or persisted in
  fixtures, prompts, or provenance.

### Company validation

- Investment Thesis companies must belong to the approved canonical company
  registry.
- Arbitrary ticker values are not accepted.

### Company groups

- A company group is one Investment Thesis assigned to multiple companies.
- Named, reusable company-group records are out of scope.

### Baseline error handling

- No custom, production-style error envelope is required.
- Request-schema validation uses the framework validation response.
- An operation for a resource that does not exist returns HTTP `404`.
- Duplicate account email returns HTTP `409` with detail `email in use`.

### Account and thesis HTTP contract

- `Inżynierka docs.md#account-and-investment-thesis-schemas` defines the
  accepted request and response JSON for account and thesis CRUD.
- Investment Thesis updates use
  `PUT /user/strategy/{thesis_id}?api_key={api_key}`.

## Clarifications

### Thesis identifier

A `thesis_id` is the stable identifier of one user-owned Investment Thesis.
It is not an investment strategy value. It lets the API update the same thesis
after its description, risk tolerance, horizon, style, or assigned companies
change. It also avoids trying to use a changing company list as a database
primary key.

The accepted schema uses a server-generated UUID thesis ID. The API route that
supplies that ID when updating a thesis remains open below.

### Company groups

The project mentions company groups in:

- `Inżynierka docs.md`, functional requirements and strategy endpoints;
- `THESIS_DECISIONS.md`, Investment Thesis section;
- `ARCHITECTURE.md`, requirements and API surface;
- `FEATURES.yaml`, `FEAT-009` scope.

The accepted schema defines a group as one thesis assigned to several approved
companies. It intentionally has no reusable, named group entity.

## Legacy Database Draft

`Sentiment_AI_create.sql` and `Sentiment_AI-2026-08-16_12-46.png` are retained
with this decision record as reference artifacts. `Sentiment_AI_create_expanded.sql`
is the accepted PostgreSQL schema reference for future migrations. It does not
overwrite the legacy export or serve as an applied migration.

The draft is useful for the base relationships among users, companies, reports,
chunks, prices, and historical predictions. It is not a final schema for the
current thesis architecture:

- `users.user_id` is an integer, while the account decision requires a
  server-generated UUID and an API-key digest.
- `strategies` plus `subscriptions` model a reusable named strategy per
  user/company; they cannot store one structured, user-owned thesis with risk
  tolerance, investment horizon, investment style, description, and a
  multi-company assignment.
- `reports` and `chunks` do not retain the raw/cleaned source content,
  source identifier, source type, document type, or full document lineage
  required by the architecture.
- `past_predictions` stores only a document link and timestamp; it lacks the
  scores, evidence, dates/horizons, run ID, and provenance required for an
  auditable prediction.
- The draft has no tables for chunk scores, company snapshots, experiment
  runs, or secret-free provenance.

The accepted expanded schema should inform `FEAT-008` migrations, rather than
be copied as the migration itself.

### Accepted persistence reference

`Sentiment_AI_create_expanded.sql` defines the accepted data-model direction:

- UUID-backed users and Investment Theses;
- a one-way API-key digest;
- company registry validation;
- multi-company thesis assignment;
- raw and cleaned documents with immutable chunk lineage;
- append-only score, snapshot, prediction, evidence, run, and provenance
  records.
