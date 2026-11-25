# Assumptions and open decisions

## Hosted portal direction, 2026-11-25

- The local launcher opens the weekly-plan portal as the primary app and keeps the older encrypted workbook workspace on a separate loopback port. The portal preview is synthetic and has a separate account and database; real client access still requires the India-hosted HTTPS release gate. At the coach's request, the loopback SQLite preview auto-opens as coach without password or MFA. This explicit flag is absent in public deployment, where command-line registration and MFA remain required. Weekly updates are assigned as new published weeks so earlier actuals remain visible.

- The coach changed the MVP direction to a hosted mobile web app. One coach builds and imports reusable programs, publishes immutable versions, assigns client-specific copies, and invites clients with one-time links. Clients enter and correct their own prescribed-set actuals and weekly recovery; corrections retain history. This supersedes D-01, D-02, D-03, D-05, D-07, ADR-001, ADR-002, and ADR-006 for the **new hosted runtime**. The local runtime remains a migration source.
- The coach selected one coach account, scheduled assignments from a start date, prescribed sets only, India-hosted training data, AI later, and free hosting for now. If OCI Mumbai Always Free capacity is unavailable, work remains local until free capacity is available. Netlify was considered for the frontend; the coach chose one Mumbai server for site and API.
- Hosted code and synthetic checks are under implementation. No public deployment, real-data transfer, backup restore, performance measurement, or client invitation has been completed. Transfer requires a reviewed encrypted export and explicit import; no workbook binaries or credentials are included.

## Reusable training-grid mappings, 2026-11-25

- The importer now suggests training tabs by finding repeated `Week N` / `sets` headers beyond the first row. The coach can change selected tabs, header rows, day/exercise columns, week columns, block labels, units, and aliases before a read-only mapped-set preview. Only an explicit mapping approval followed by commit writes canonical sets.
- Numeric target ranges are stored as prescription bounds. Nonnumeric actual cells and zero-rep outcomes require individual coach decisions; the source value remains in lineage. An approved structural profile can be offered on a corrected workbook, but snapshot-specific cell corrections are cleared and must be reviewed again.
- The new mapping shape is version 2 inside existing profile JSON, so no database migration is needed. Legacy profile fingerprints and extraction defaults remain available. Mixed workbooks may still need coach selection or new format support; this is not a claim that every Excel layout imports automatically.
- A read-only pass over the local diagnostic workbook found 11 candidate training tabs, 5,607 candidate sets, and 2,311 blocking findings after row-order set numbering. Most need individual numeric or missing-value decisions. These counts describe a draft over all suggested tabs, not coach-approved canonical data or a completed real-workbook acceptance test.

## Workbook preview limit, 2026-11-25

- A local `.xlsx` upload failed preview solely because three worksheets extended beyond the 100-column cap; the widest had 157 columns. The workbook has 15 sheets, stays below 10 MB, and previewed in 7.5 seconds with a 200-column cap. The cap is now 200; the 20,000-row, 30-sheet, 10 MB upload, and archive expansion limits remain. This diagnostic preview did not approve a mapping or commit training data. Full AT-02 sign-off still needs coach-approved reference workbooks.

## Security and UX implementation, 2026-11-25

- The coach selected local-only operation, a performance studio design for current screens, encrypted database and backups, a recovery passphrase, LocalAppData storage, and a coach-selected backup destination.
- SQLCipher 4 stores the canonical data and retained workbooks in one encrypted database. Alembic revision 0002 adds workbook snapshots. The key and local coach credentials use user-scoped Windows DPAPI. Optional integration secrets use Windows Credential Manager.
- Backup exports a consistent SQLCipher transaction, compares all table records, and checks database integrity. Restore requires an unused destination and creates a new Windows-protected key. The coach creates a new local login after restore and reconnects integrations.
- The existing workspace was migrated to LocalAppData and both database and Ollama health checks passed. Original OneDrive files remain for rollback and require deliberate cleanup after backup verification.
- Seventeen automated tests passed, including migration rollback, encrypted reopen, incorrect passphrase rejection, restore, login expiry/throttling, request boundaries and athlete/source scoping. Frontend build passed. Browser walkthroughs with synthetic responses passed at 1440, 390 and 320 CSS pixels. Screen-reader testing and a complete real-data acceptance run remain outstanding.
- Gitleaks found no secrets in staged source, fetched remote history, or the built frontend. This is a scan result, not a guarantee against all disclosure.
- GitHub origin points to hsbhamarah/StrengthAI. Its existing README history is preserved as the parent of the local implementation. The repository was public when checked. Changing visibility and pushing require GitHub device authorization.

## Verified decisions from the referenced conversation

| ID | Decision |
| --- | --- |
| D-01 | Fully local application on an existing Windows laptop with 8 GB RAM. |
| D-02 | React + TypeScript + Vite, FastAPI, SQLite, SQLAlchemy/Alembic, local Ollama. v0.6 supersedes v0.5 PostgreSQL/Docker baseline. |
| D-03 | Single coach, multiple athletes; coach dashboard access only. |
| D-04 | Variable Excel and Google Sheets training workbooks; reusable, coach-approved mappings. |
| D-05 | Mandatory weekly recovery check-ins through existing athlete Google Sheets. This supersedes v0.4's athlete-facing local form/link concept. |
| D-06 | Hybrid AI: automated weekly reviews plus conversational questions. Recommendations require coach decision and never edit a program automatically. |
| D-07 | The one local coach creates an email/password account on a first-run sign-up page, then signs in on a dedicated sign-in screen (coach requests, 2026-11-25). |

## Assumptions used to make this package implementable

| ID | Assumption | Validation needed |
| --- | --- | --- |
| A-01 | Windows 11 and Python 3.12 are target development/runtime versions. | Confirm OS/build and deployment constraints. |
| A-02 | One coach uses one local application instance; no concurrent remote coach access. | Confirm workflow. |
| A-03 | Training weeks use a stable source week key and numeric order; local start/end dates and timezone may be assigned later. | Confirm boundaries before deadline/late calculations. |
| A-04 | Loads are stored canonically in kilograms; imported units and raw values remain traceable. | Confirm kg/lb handling. |
| A-05 | RPE uses 0–10, RIR uses nonnegative decimal; conversions are not automatic without a coach-approved rule. | Confirm actual templates. |
| A-06 | One current recovery row per athlete/week, with immutable revisions. | Confirm whether multiple check-ins per week are needed. |
| A-07 | OAuth uses the coach's Google account to read athlete-shared sheets; the app writes nothing to them. | Confirm sharing/ownership arrangement. |
| A-08 | The SQLite schema is a starter physical contract; SQLAlchemy/Alembic migrations become authoritative once coded. | Validate against reference workbooks. |

## Open decisions / requested inputs

| ID | Decision needed | Impact |
| --- | --- | --- |
| O-01 | Provide representative Excel/Sheets workbooks, including top sets, back-offs, percentage and RPE prescriptions, failed/skipped/missing actuals. | Mapping and schema validation; P0 blocker for real ingestion sign-off. |
| O-02 | Define actual week boundaries, check-in due window/deadline, and whether the submitted date is athlete-entered. | Check-in state/late rules. |
| O-03 | Confirm exercise alias list and which variations are comparable for trend/e1RM views. | Metric grouping. |
| O-04 | Agree e1RM formula and eligibility, plus rule thresholds for persistent RPE overshoot/fatigue. | Analytical sign-off. Defaults in `ANALYTICS.md` are provisional. |
| O-05 | Define retention periods, external backup location, and acceptable recovery point/time. | Privacy and operations. |
| O-06 | Select final Ollama model after measured structured-output, evidence, latency, and RAM tests on the actual laptop. | AI defaults. |
| O-08 | Confirm pain/instability wording and coach escalation workflow. | Safety messaging. |

## Provenance gap

The provided referenced thread exposes v0.4–v0.6 and an Ollama revision, but not original v0.1–v0.3 source text. This package includes only requirements supportable from the accessible thread and flags new details as assumptions. If earlier versions are supplied, reconcile them here before treating the package as a complete historical consolidation.

## Implementation status, 2026-11-16

- The coach chose the full P0 MVP as the target and synthetic fixtures first. Documented coaching rules remain provisional until reviewed before real-data release.
- An early M0–M2 slice has been added. It does not yet satisfy the full P0 scope. In particular, the durable worker, complete schema/API contract, Google Sheets, Ollama, recommendation decisions, encrypted backup/restore, and Windows performance gate remain open.
- Package installation was blocked in this workspace by network restrictions. Python syntax and dependency-light ingestion/metric tests ran, but API, migration, and frontend builds have not run.
- Week intervals are optional for training import. Exercise aliases require approval; unexplained source deletions block commit. The coach-approved zero-rep rule for this tracker maps zero actual reps to skipped.
- The Excel re-import UI now lists athlete-owned workbook sources. The semantic set key excludes set type, so a top/back-off correction revises the existing set rather than making a duplicate. API and Alembic integration tests remain unverified until dependencies are available.
- The coach supplied a local reference workbook for inspection. It remains ignored by Git and must not be copied into committed fixtures. Its two training grids cover Weeks 1–5 and 7–12; Week 6 is intentionally absent from this import. The current preview flattens 11 week groups and keeps limb values separate, ordered right then left.
- For this tracker, the Load cell is also actual load when actual reps are present. A zero in Actual Reps means skipped/not attempted; any leftover RPE or load is retained as raw lineage but excluded from canonical performance. The coach clarified that Excel `d-m` values alongside an exercise represent ranges in the corresponding Reps, RIR, or RPE column. The parser stores lower and upper bounds and retains the raw date-formatted value. Other date formats remain unresolved.
- The coach deferred week start/end dates. Training weeks now use stable `week_key` values and may be imported without dates. Check-in deadline and late calculations remain unavailable until dates and due rules are supplied. The coach must still review the exercise aliases and recovered range bounds before real-data import sign-off.
- The React frontend now covers the available local API slice: sign-in, athlete selection and creation, initial dashboard metrics, training sets, and Excel import approval. The import preview API still returns raw cell samples rather than the full canonical rows that a coach should review; real-data import sign-off remains open. The frontend build could not be run in this sandbox because npm package downloads were denied.

## Local runtime check, 2026-11-25

- The API and frontend build ran locally, the database migration completed, and the core tests passed after package installation. Ollama 0.40.18 was already reachable on loopback; API health now reports its actual reachability and the contracted model discovery endpoint is implemented.
- This laptop has 7.7 GB RAM. The installed 27B model is too large for the planned 8 GB target; `qwen3:1.7b` is installed as a low-memory candidate. This does not select a final AI default or close O-06. Model quality, peak memory, and latency gates still require the M4 benchmark. AI reviews and coach decisions remain unimplemented.
- The coach login now requires both an email and password. First-run local setup stores the normalized email beside the existing Argon2 password hash under ignored `data/`; an existing password-only setup can add its email after verifying the current password. This changes no database schema.
- First-run account creation is also available from `/sign-up` while no coach credential files exist. Later sign-up attempts are rejected; the terminal setup path remains for existing password-only accounts.
