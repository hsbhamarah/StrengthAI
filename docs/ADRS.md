# Architecture decision records

Each record is accepted for the MVP unless an open decision in `DECISIONS.md` changes it.

## ADR-001 — Local-first process topology

**Decision:** Built Vite UI served by FastAPI at loopback; Python service handles API, ingestion, analytics, jobs, and AI orchestration. Ollama runs separately on loopback. Google Sheets is the sole routine external integration. **Reason:** Works on one coach's Windows laptop, permits offline Excel/analytics/AI, and avoids public service exposure. **Consequences:** The laptop must be on for sync; no athlete access to the coach app.

## ADR-002 — SQLite system of record

**Decision:** SQLite with foreign keys enabled per connection, WAL mode, busy timeout, short transactions, and one controlled writer/job worker. Use SQLAlchemy and Alembic. **Reason:** v0.6 8 GB footprint and single coach usage. **Consequences:** Keep writes serialized; use SQLite backup API for consistent backups; revisit PostgreSQL only for multi-user/remote deployment.

## ADR-003 — Canonical ingestion with lineage

**Decision:** Source-specific parsers and coach-approved mapping profiles produce canonical prescriptions, actuals, and recovery rows. Preserve raw cell addresses/values, source fingerprints, import jobs, revisions and validation findings. **Reason:** Workbook layouts vary and mappings can be wrong. **Consequences:** No silent auto-commit or destructive re-import.

## ADR-004 — Deterministic analytics, bounded AI

**Decision:** Python calculates all metrics and rules. Ollama receives compact, scoped evidence and emits structured findings; backend validates every evidence ID, scope, action and safety condition. **Reason:** LLMs can fabricate calculations. **Consequences:** AI can be unavailable while dashboards still work; model has no direct SQL/files/network/write access.

## ADR-005 — Coach decision boundary

**Decision:** Recommendations are immutable proposals with status derived from coach decisions. No prescription write-back endpoint in MVP. **Reason:** Coaching authority stays with the human. **Consequences:** Approval records intent; changing a program happens in the source workbook outside StrengthOS until a future separately approved workflow exists.

## ADR-006 — Google Sheets check-ins

**Decision:** Read-only Google Sheets sync; dedicated `Recovery Check-in` worksheet with a stable weekly row ID and validation rules. Manual sync first, optional polling while app runs. **Reason:** Athletes use existing shared sheets. **Consequences:** Internet required for sync; athlete-entered dates are not independently verified submission timestamps.

## ADR-007 — Persistent single-worker jobs

**Decision:** DB-backed queue with `queued/running/completed/failed/cancelled`, idempotency keys, checkpoints and restart recovery. One worker serializes imports, sync, recalculation, analysis and backups; AI concurrency one. **Reason:** Long jobs can outlive a request or be interrupted. **Consequences:** Some jobs wait; UI displays progress and failure reason.
