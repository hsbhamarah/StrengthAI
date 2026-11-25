# Prioritized implementation backlog

## Hosted portal pivot (priority over the legacy backlog below)

| Order | Work item | Done when |
| --- | --- | --- |
| H1 | Portal schema, secure account/invite/session boundary, templates and publishing | Fresh and upgraded migrations pass; coach/client scope and publish immutability pass contract tests. |
| H2 | Client actuals, recovery, revisions and mobile UI | Two invited clients log separate programs; corrections preserve history; missing/failed/skipped remain distinct. |
| H3 | Coach-approved Excel-to-draft path and encrypted local transfer | Preview and hash approval precede draft creation; reviewed transfer excludes workbook binaries/credentials and imports into a fresh database. |
| H4 | Mumbai deployment, HTTPS, restricted database, daily backups and restore | Region and free-resource status verified; backup restored to separate DB; real-client invitation gate passes. |
| H5 | Security, accessibility, performance and acceptance | Cross-client, MFA, CSRF, upload, mobile, backup, and target-VM checks measured and recorded. |

The old M3 Google Sheets and M4 Ollama items follow the portal data path if still wanted. They are not portal release blockers.

Each item is an independently reviewable slice. `P0` is required for MVP; `P1` follows a working MVP. Dependencies refer to item IDs. Use synthetic fixtures until real workbook access is approved.

| ID | Priority | Work item | Depends on | Done when |
| --- | --- | --- | --- | --- |
| M0-01 | P0 | Scaffold React/TS/Vite and FastAPI monorepo; local development commands and built-UI serving. | — | App starts on loopback with health page. |
| M0-02 | P0 | SQLAlchemy models, Alembic initial migration, SQLite pragmas, repository layer. | M0-01 | Fresh DB and migration upgrade/downgrade work; FK enforcement verified. |
| M0-03 | P0 | Local coach login/session/CSRF and secure config paths. | M0-01 | Unauthenticated writes rejected; no bundled credentials. |
| M0-04 | P0 | Persistent single-worker queue, retry/lease/restart handling. | M0-02 | Interrupted job recovers without duplicate effects. |
| M1-01 | P0 | Athlete/block/week/session/exercise CRUD and exercise alias mapping. | M0-02, M0-03 | One coach manages two athletes with isolated records. |
| M1-02 | P0 | Excel snapshot parser, limits, preview, validation issue model. | M0-04, M1-01 | Two synthetic layouts previewed; malformed file fails safely. |
| M1-03 | P0 | Mapping wizard, profile versioning, explicit approval/commit. | M1-02 | Critical ambiguity blocks commit; coach can correct mapping. |
| M1-04 | P0 | Canonical prescribed/actual storage, source lineage, revisions and idempotent re-import. | M1-03 | Unchanged import no-ops; changed RPE revises and invalidates metrics. |
| M2-01 | P0 | Deterministic metrics and rule engine with independent vectors. | M1-04 | `ANALYTICS.md` vectors pass; evidence and sample counts returned. |
| M2-02 | P0 | Coach dashboard, history, analytics, data quality center and drill-down. | M2-01 | Flags link to source cell and calculation. |
| M3-01 | P0 | Google desktop OAuth, source registration and manual read-only sync. | M0-03, M0-04, M1-03 | Authorized Sheet imports; network failure retains last snapshot. |
| M3-02 | P0 | Recovery worksheet parser, revision history, due states and symptom flag. | M3-01 | Correct athlete/week association; missing check-in qualifies review. |
| M4-01 | P0 | Ollama discovery/settings and benchmark harness for 8 GB machine. | M0-01, M0-04 | Installed models shown; candidate report records RAM/latency/quality. |
| M4-02 | P0 | Evidence packet builder, structured review, validation and safe fallback. | M2-01, M3-02, M4-01 | Unknown/cross-athlete IDs rejected; offline metrics remain. |
| M4-03 | P0 | Scoped AI chat and recommendation review queue/coach decisions. | M4-02 | Decisions audited; prescriptions unchanged. |
| M5-01 | P0 | Consistent encrypted backup and tested restore. | M0-02, M1-04 | Clean instance recovers athletes, training, check-ins, decisions. |
| M5-02 | P0 | Security/privacy review, Windows packaging and performance UAT. | All P0 | All `ACCEPTANCE.md` P0 cases pass with documented measurements. |
| M5-03 | P1 | Configurable Sheets polling while app is running. | M3-01 | Schedule stops when app closes; errors visible. |
| M5-04 | P1 | Coach-configurable rule thresholds and retention workflow. | M2-01, O-05 | Changes versioned and audited. |

## Suggested milestones

1. Data foundation: M0 + M1. Deliver a running local vertical slice before AI work.
2. Analytical MVP: M2 with tested metrics and traceable dashboard.
3. Recovery: M3 with manual Sheets sync and mandatory weekly state.
4. AI: M4 after evidence pipeline is reliable.
5. Release: M5 plus all P0 acceptance and performance checks.

## Required decisions at gates

Before M1 real workbook sign-off: O-01/O-02/O-03. Before M2 rule sign-off: O-04. Before M4 model default: O-06. Before release: O-05/O-08. See `DECISIONS.md`.
