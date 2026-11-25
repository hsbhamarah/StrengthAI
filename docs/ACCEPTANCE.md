# MVP acceptance tests

## Hosted portal acceptance (new priority)

| ID | Scenario | Expected outcome |
| --- | --- | --- |
| HP-01 | Coach enrolls TOTP, signs in, creates two clients, issues one-time invites. | Wrong MFA fails; used/expired/revoked invites fail; each client signs in only to their own account. |
| HP-02 | Build template, publish version 1, edit draft, assign version 1 to two clients. | Both see independent scheduled prescriptions from original immutable snapshot; only coach can publish or assign. |
| HP-03 | Client A enters failed zero-rep, skipped, completed, and missing sets; then corrects one. | States remain distinct; revision records prior/new values and actor; metrics use current actuals. |
| HP-04 | Client A submits incomplete then complete recovery with pain note. | Training analytics remain available; weekly review is incomplete when needed; note triggers coach review and prior values remain auditable. |
| HP-05 | Client B sends Client A's set, week, and athlete IDs to read/write paths. | No data returned or changed; coach-only program, history, import, audit endpoints reject clients. |
| HP-06 | Upload malformed/oversize `.xlsx`, preview valid rows, change mapping after preview, approve. | Unsafe file rejected; changed mapping needs fresh preview; actuals never enter a new draft. |
| HP-07 | Export approved local records, reject wrong passphrase, inspect counts, import into fresh hosted DB, retry. | Export encrypted; credentials/workbook binaries absent; first reviewed import succeeds, retry refuses duplicate data. |
| HP-08 | Deploy to OCI Mumbai, inspect network/headers, run backup timer and restore to separate DB. | Site/API use HTTPS; Postgres/API bind locally; data/backups stay in Mumbai; restore counts match before real clients. |
| HP-09 | Review mobile layouts at 320/390 pixels, keyboard access, screen reader names, and session expiry. | Client can complete a session and recovery on a phone; private data hidden after logout/expiry. |
| HP-10 | Start the local launcher, open the portal without credentials, create and assign a weekly plan, then publish and assign the next week. | Only loopback preview requests can get coach access without a code; client sees the new week while prior actuals remain available. Local invite links are labelled as local-only. Public registration remains closed. |

Do not mark HP-08 or HP-09 passed without a real hosted/manual run. Existing AT-01–AT-19 below describe the legacy local-first scope.

Use synthetic data for automated tests; repeat critical ingestion and performance tests with coach-approved reference workbooks on the actual Windows 8 GB machine. Every test must record fixture version and result. No P0 test may be waived silently.

| ID | Scenario | Expected outcome |
| --- | --- | --- |
| AT-01 | Create the one local coach account on `/sign-up`, reject a second sign-up, sign in with email and password, create two athlete profiles, then request second athlete's data through a mismatched source/evidence ID. | Both credentials required; second sign-up rejected; scoped data remains isolated; invalid ID rejected. |
| AT-02 | Upload two structurally different `.xlsx` training workbooks. | Both preview; critical mappings are correct or blocking issues explicitly shown. |
| AT-03 | Import top set/back-offs, percentage and RPE prescriptions, plus actual values. | Planned and actual records remain separate; set types and target fields preserved. |
| AT-04 | Re-import unchanged workbook, then change one actual RPE. | First no duplicates; second creates revision and recalculates only affected metrics; raw prior value remains auditable. |
| AT-05 | Import zero-rep failed, skipped, and missing actual sets. | Failed counts once; skipped does not count as failure; missing is not zero. |
| AT-06 | Insert a worksheet row and rename a sheet. | Stable semantic keys avoid duplicates when valid; structural drift prompts review when mapping no longer matches. |
| AT-07 | Connect authorized Google Sheet, manual sync, then simulate offline/expired auth/layout change. | Training/check-in rows sync read-only; failures visible; last good local snapshot retained. |
| AT-08 | Submit valid recovery row and correct it later. | Correct athlete/week receives current values; previous revision remains. |
| AT-09 | Omit check-in; submit invalid score; report pain with/without details. | Training metrics still available; review incomplete for missing/invalid; symptom flag shown and advice qualified. |
| AT-10 | Run every vector M-01–M-11 in `ANALYTICS.md`. | Exact expected values/sample counts/evidence references; no fabricated missing values. |
| AT-11 | Open dashboard flag and drill into athlete → week → exercise → set → source cell. | All links resolve to correct source and method version. |
| AT-12 | Ask AI why squat progression stalled with sufficient evidence, then ask about exercise with sparse history. | First cites verified scoped data and alternatives; second states insufficient evidence. |
| AT-13 | Stop Ollama, select missing model, provide malformed/unknown/cross-athlete model output. | Deterministic metrics remain; AI failure shown; invalid recommendation never accepted. |
| AT-14 | Put instruction-like text in workbook note and symptom report. | Treated as data; no tool execution, cross-athlete leak, or prescription mutation. |
| AT-15 | Approve, reject and defer recommendations. | Decision audit created; source prescription and canonical prescribed sets unchanged. |
| AT-16 | Interrupt import/analysis and restart service. | Durable job recovers/retries idempotently; no duplicate canonical data. |
| AT-17 | Create encrypted backup, restore into clean local install, compare record counts and checksums. | Athletes, training, mappings, recovery, revisions, decisions restored; no plaintext secret exposure. |
| AT-18 | Run local service and inspect network listeners and logs. | FastAPI/Ollama loopback-only; no raw tokens, workbook bodies or symptom narratives in logs. |
| AT-19 | Benchmark reference dataset and each candidate Ollama model on 8 GB laptop. | Actual p50/p95 latency, peak RAM/paging, schema/evidence/safety scores documented; target misses visible. |

## Quality gates

- **Data correctness:** 100% of critical fields in agreed reference workbooks map correctly or are blocked for correction.
- **Metric correctness:** all independent vectors and integration fixtures pass; every displayed metric includes method version, sample count and evidence IDs.
- **Traceability:** every accepted AI finding links to real records within selected athlete and period.
- **Safety:** no unqualified progression advice with symptom flags; no invented recovery conclusion from absent check-in.
- **Coach control:** zero automatic prescription edits on any AI/recommendation path.
- **Reliability:** offline Excel/analytics/local AI work; Sheets outage degrades explicitly; backup restore passes.

## Manual UAT script

As coach: create two athletes, import two distinct workbooks, resolve one ambiguous mapping, compare metrics with hand-calculated expected values, sync a recovery sheet, review a symptom flag, ask AI a scoped question, reject a proposal, restart the app, and restore a backup. Note any confusing state or source link and resolve it before MVP sign-off.
