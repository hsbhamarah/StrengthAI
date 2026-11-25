# StrengthOS AI — PRD / SRS

**Status:** implementation baseline from accessible v0.4–v0.6 design; validate against real workbooks. **Product owner:** coach. **MVP platform:** Windows 8 GB local laptop.

## Goal and actors

Give one strength coach a traceable view of multiple athletes' prescribed versus actual training, recovery, performance trends, and AI-assisted review. The coach owns every programming decision. Athletes enter weekly recovery data in their existing Google Sheets; they have no StrengthOS coach-workspace accounts in the MVP.

## Scope

**MVP:** local startup/login, athlete directory and overview, training source setup, Excel import and Sheets sync, mapping wizard, validation center, training history, deterministic analytics, recovery history/status, weekly analysis, AI chat, recommendation queue/decisions, settings, audit history, backup/restore.

**Later:** end-of-block report, intervention outcome comparisons, reminders, complete next-block proposals, program write-back, remote/multi-coach hosting. Do not build public athlete form/link from v0.4; v0.6 chose Sheets.

## Functional requirements

| ID | Priority | Requirement | Acceptance link |
| --- | --- | --- | --- |
| FR-01 | P0 | Coach logs in locally and manages multiple athlete profiles, goals, blocks, weeks, sessions and exercises. | AT-01 |
| FR-02 | P0 | Upload `.xlsx` (and agreed `.xls` conversion path if needed), preview variable layouts, approve reusable mapping profiles, and show row/cell validation. | AT-02, AT-03 |
| FR-03 | P0 | Import prescription and actual data separately, including top/back-off sets, target RPE/RIR, percentages, reference strength, and failed/skipped/unreported states. | AT-03–AT-06 |
| FR-04 | P0 | Re-import idempotently; changed source values create revisions and recalculate affected metrics. | AT-04 |
| FR-05 | P0 | Read authorized athlete Google Sheets for training actuals and recovery rows; report sync failures and layout drift without corrupting prior data. | AT-07 |
| FR-06 | P0 | Require a recovery check-in per defined training week, track states and symptom flags, preserve corrections. | AT-08, AT-09 |
| FR-07 | P0 | Calculate metrics in Python from validated records and show method, sample count, missingness, and evidence links. | AT-10 |
| FR-08 | P0 | Coach dashboard flags progress, missing data, safety review and pending decisions; drill down to athlete/week/exercise/set/source cell. | AT-11 |
| FR-09 | P0 | Generate weekly AI review and answer scoped coach questions using verified metrics and source references; state uncertainty. | AT-12–AT-14 |
| FR-10 | P0 | Coach can approve/reject/defer a recommendation; decision is audited and never changes prescriptions automatically. | AT-15 |
| FR-11 | P0 | Select installed Ollama model and handle unavailable/invalid output safely. | AT-13 |
| FR-12 | P0 | Create and restore verified local backups. | AT-17 |
| FR-13 | P1 | Poll selected Sheets while app is running; configure thresholds and review preferences. | AT-07 |

## Screens and navigation

Coach dashboard → athlete directory → athlete overview → training history / analytics / recovery / AI assistant. Global data sources → import preview → mapping wizard → data quality center. Global review queue → recommendation detail → coach decision. Settings → AI model, rules, privacy, backup. Responsive mobile layout is required for coach read/review use, but desktop is primary.

## Behavioral rules

- A missing check-in leaves weekly review `incomplete`; performance analytics still run. AI must not infer recovery state from missing data.
- A new or worsening pain/instability report creates a prominent coach-review flag; ordinary progression advice must be qualified.
- No trend claim from fewer than the configured comparable exposures; no mixing exercise variants without an approved equivalence rule.
- An AI response with unknown evidence IDs, cross-athlete IDs, invalid schema, or prohibited actions is rejected and shown as unavailable or needs review, never silently accepted.
- Original imports and revisions remain auditable. Correcting a mapping triggers selective recalculation.

## Nonfunctional requirements

| ID | Target / gate |
| --- | --- |
| NFR-01 | Bind FastAPI and Ollama to loopback; no public ports by default. |
| NFR-02 | Excel import, existing dashboards/metrics, and installed-model AI work without internet. |
| NFR-03 | Typical athlete dashboard <3 s, standard analytics query <2 s, reference workbook import <30 s; provisional until reference data and laptop benchmark. |
| NFR-04 | Preferred first AI response <15 s and weekly review <90 s on target laptop; record measured cold/warm latency and treat misses as tuning input, not concealed failures. |
| NFR-05 | AI concurrency 1; initial context cap 4096 tokens, bounded output, idle unload. |
| NFR-06 | Database survives restart; interrupted jobs recover; unchanged imports do not duplicate canonical rows. |
| NFR-07 | All metric calculations pass independently checked reference vectors; all critical mapping fields are correct or flagged. |
| NFR-08 | No real athlete data, credentials, or unredacted health notes in repository/logs/model benchmark corpus. |

## Data and interface contracts

See `db/schema.sql`, `db/ERD.md`, `api/openapi.yaml`, `INGESTION.md`, `ANALYTICS.md`, and `RECOVERY_SHEETS.md`. The API lives under `/api/v1`; FastAPI-generated OpenAPI must be contract tested against the baseline file.

## Release gate

Run every P0 scenario in `ACCEPTANCE.md` on synthetic fixtures and representative consented workbooks. Measure model behavior on the actual 8 GB device. Restore a backup to a clean local instance. Confirm no prescription changes on recommendation approval. Resolve open decisions that affect data interpretation before release.
