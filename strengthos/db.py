from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.types import Float, Integer, LargeBinary, String, Text


class Base(DeclarativeBase):
    pass


def id_column():
    return mapped_column(String(36), primary_key=True)


class Athlete(Base):
    __tablename__ = "athletes"
    athlete_id: Mapped[str] = id_column()
    display_name: Mapped[str] = mapped_column(String(120))
    goal: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[str] = mapped_column(String(40))


class TrainingBlock(Base):
    __tablename__ = "training_blocks"
    block_id: Mapped[str] = id_column()
    athlete_id: Mapped[str] = mapped_column(ForeignKey("athletes.athlete_id"), index=True)
    label: Mapped[str] = mapped_column(String(120))
    phase: Mapped[str] = mapped_column(String(40))
    start_date: Mapped[str | None] = mapped_column(String(10))
    end_date: Mapped[str | None] = mapped_column(String(10))


class TrainingWeek(Base):
    __tablename__ = "training_weeks"
    week_id: Mapped[str] = id_column()
    block_id: Mapped[str] = mapped_column(ForeignKey("training_blocks.block_id"), index=True)
    week_key: Mapped[str] = mapped_column(String(120))
    week_index: Mapped[int] = mapped_column(Integer)
    start_date: Mapped[str | None] = mapped_column(String(10))
    end_date: Mapped[str | None] = mapped_column(String(10))
    checkin_due_at: Mapped[str | None] = mapped_column(String(40))
    __table_args__ = (UniqueConstraint("block_id", "week_key"), UniqueConstraint("block_id", "week_index"))


class Session(Base):
    __tablename__ = "sessions"
    session_id: Mapped[str] = id_column()
    week_id: Mapped[str] = mapped_column(ForeignKey("training_weeks.week_id"), index=True)
    session_date: Mapped[str | None] = mapped_column(String(10))
    label: Mapped[str] = mapped_column(String(120))
    ordinal: Mapped[int] = mapped_column(Integer)


class Exercise(Base):
    __tablename__ = "exercises"
    exercise_id: Mapped[str] = id_column()
    canonical_name: Mapped[str] = mapped_column(String(120), unique=True)
    movement_group: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[str] = mapped_column(String(40))


class ExercisePrescription(Base):
    __tablename__ = "exercise_prescriptions"
    prescription_id: Mapped[str] = id_column()
    session_id: Mapped[str] = mapped_column(ForeignKey("sessions.session_id"), index=True)
    exercise_id: Mapped[str] = mapped_column(ForeignKey("exercises.exercise_id"))
    source_label: Mapped[str | None] = mapped_column(String(120))
    ordinal: Mapped[int] = mapped_column(Integer)
    notes: Mapped[str | None] = mapped_column(Text)


class PrescribedSet(Base):
    __tablename__ = "prescribed_sets"
    prescribed_set_id: Mapped[str] = id_column()
    prescription_id: Mapped[str] = mapped_column(ForeignKey("exercise_prescriptions.prescription_id"), index=True)
    set_index: Mapped[int] = mapped_column(Integer)
    side: Mapped[str] = mapped_column(String(10), default="both")
    set_type: Mapped[str] = mapped_column(String(20))
    target_reps: Mapped[float | None] = mapped_column(Float)
    target_reps_min: Mapped[float | None] = mapped_column(Float)
    target_reps_max: Mapped[float | None] = mapped_column(Float)
    target_load_kg: Mapped[float | None] = mapped_column(Float)
    target_rpe: Mapped[float | None] = mapped_column(Float)
    target_rpe_min: Mapped[float | None] = mapped_column(Float)
    target_rpe_max: Mapped[float | None] = mapped_column(Float)
    target_rir: Mapped[float | None] = mapped_column(Float)
    target_rir_min: Mapped[float | None] = mapped_column(Float)
    target_rir_max: Mapped[float | None] = mapped_column(Float)
    percent_1rm: Mapped[float | None] = mapped_column(Float)
    reference_1rm_kg: Mapped[float | None] = mapped_column(Float)
    __table_args__ = (UniqueConstraint("prescription_id", "set_index", "side"),)


class ActualSet(Base):
    __tablename__ = "actual_sets"
    actual_set_id: Mapped[str] = id_column()
    prescription_id: Mapped[str] = mapped_column(ForeignKey("exercise_prescriptions.prescription_id"), index=True)
    prescribed_set_id: Mapped[str | None] = mapped_column(ForeignKey("prescribed_sets.prescribed_set_id"), unique=True)
    set_index: Mapped[int] = mapped_column(Integer)
    side: Mapped[str] = mapped_column(String(10), default="both")
    status: Mapped[str] = mapped_column(String(20))
    reps: Mapped[float | None] = mapped_column(Float)
    load_kg: Mapped[float | None] = mapped_column(Float)
    actual_rpe: Mapped[float | None] = mapped_column(Float)
    actual_rir: Mapped[float | None] = mapped_column(Float)
    is_extra: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[str] = mapped_column(String(40))
    __table_args__ = (CheckConstraint("status <> 'skipped' OR (reps IS NULL AND load_kg IS NULL AND actual_rpe IS NULL)"),)


class DataSource(Base):
    __tablename__ = "data_sources"
    source_id: Mapped[str] = id_column()
    athlete_id: Mapped[str] = mapped_column(ForeignKey("athletes.athlete_id"), index=True)
    kind: Mapped[str] = mapped_column(String(20))
    display_name: Mapped[str] = mapped_column(String(255))
    external_id: Mapped[str | None] = mapped_column(String(255))
    active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(String(40))


class MappingProfile(Base):
    __tablename__ = "mapping_profiles"
    mapping_id: Mapped[str] = id_column()
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.source_id"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    layout_fingerprint: Mapped[str] = mapped_column(String(64))
    mapping_json: Mapped[str] = mapped_column(Text)
    approved_at: Mapped[str] = mapped_column(String(40))
    approved_by: Mapped[str] = mapped_column(String(40))


class ImportJob(Base):
    __tablename__ = "import_jobs"
    import_id: Mapped[str] = id_column()
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.source_id"), index=True)
    mapping_id: Mapped[str | None] = mapped_column(ForeignKey("mapping_profiles.mapping_id"))
    source_snapshot_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(20))
    started_at: Mapped[str | None] = mapped_column(String(40))
    finished_at: Mapped[str | None] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(100))
    preview_json: Mapped[str | None] = mapped_column(Text)
    snapshot_path: Mapped[str | None] = mapped_column(Text)


class SourceRecord(Base):
    __tablename__ = "source_records"
    source_record_id: Mapped[str] = id_column()
    source_id: Mapped[str] = mapped_column(ForeignKey("data_sources.source_id"), index=True)
    import_id: Mapped[str] = mapped_column(ForeignKey("import_jobs.import_id"))
    mapping_id: Mapped[str] = mapped_column(ForeignKey("mapping_profiles.mapping_id"))
    natural_key: Mapped[str] = mapped_column(String(500))
    content_hash: Mapped[str] = mapped_column(String(64))
    sheet_name: Mapped[str] = mapped_column(String(255))
    cell_range: Mapped[str] = mapped_column(String(100))
    raw_json: Mapped[str] = mapped_column(Text)
    canonical_type: Mapped[str | None] = mapped_column(String(40))
    canonical_id: Mapped[str | None] = mapped_column(String(36))
    current_revision: Mapped[int] = mapped_column(Integer, default=1)
    __table_args__ = (Index("uq_source_natural_key", "source_id", "natural_key", unique=True),)


class RecordRevision(Base):
    __tablename__ = "record_revisions"
    revision_id: Mapped[str] = id_column()
    source_record_id: Mapped[str] = mapped_column(ForeignKey("source_records.source_record_id"))
    revision_no: Mapped[int] = mapped_column(Integer)
    prior_json: Mapped[str | None] = mapped_column(Text)
    new_json: Mapped[str] = mapped_column(Text)
    changed_at: Mapped[str] = mapped_column(String(40))
    reason: Mapped[str] = mapped_column(String(100))


class JobQueue(Base):
    __tablename__ = "job_queue"
    job_id: Mapped[str] = id_column()
    kind: Mapped[str] = mapped_column(String(40))
    idempotency_key: Mapped[str] = mapped_column(String(200), unique=True)
    payload_json: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[str | None] = mapped_column(String(40))
    error_code: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class Account(Base):
    __tablename__ = "accounts"
    account_id: Mapped[str] = id_column()
    athlete_id: Mapped[str | None] = mapped_column(ForeignKey("athletes.athlete_id"), unique=True)
    role: Mapped[str] = mapped_column(String(10))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    mfa_secret: Mapped[str | None] = mapped_column(String(64))
    recovery_hashes_json: Mapped[str | None] = mapped_column(Text)
    disabled_at: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40))
    __table_args__ = (CheckConstraint("(role = 'coach' AND athlete_id IS NULL) OR (role = 'client' AND athlete_id IS NOT NULL)"),)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    session_id: Mapped[str] = id_column()
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[str] = mapped_column(String(40))
    touched_at: Mapped[str] = mapped_column(String(40))
    expires_at: Mapped[str] = mapped_column(String(40))
    revoked_at: Mapped[str | None] = mapped_column(String(40))


class ClientInvite(Base):
    __tablename__ = "client_invites"
    invite_id: Mapped[str] = id_column()
    athlete_id: Mapped[str] = mapped_column(ForeignKey("athletes.athlete_id"), index=True)
    email: Mapped[str] = mapped_column(String(254))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[str] = mapped_column(String(40))
    used_at: Mapped[str | None] = mapped_column(String(40))
    revoked_at: Mapped[str | None] = mapped_column(String(40))
    created_at: Mapped[str] = mapped_column(String(40))


class ProgramTemplate(Base):
    __tablename__ = "program_templates"
    template_id: Mapped[str] = id_column()
    name: Mapped[str] = mapped_column(String(120))
    draft_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))


class TemplateImport(Base):
    __tablename__ = "template_imports"
    import_id: Mapped[str] = id_column()
    filename: Mapped[str] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(String(64))
    content: Mapped[bytes | None] = mapped_column(LargeBinary)
    created_at: Mapped[str] = mapped_column(String(40))
    expires_at: Mapped[str] = mapped_column(String(40))
    preview_mapping_hash: Mapped[str | None] = mapped_column(String(64))
    previewed_at: Mapped[str | None] = mapped_column(String(40))
    committed_at: Mapped[str | None] = mapped_column(String(40))


class ProgramVersion(Base):
    __tablename__ = "program_versions"
    version_id: Mapped[str] = id_column()
    template_id: Mapped[str] = mapped_column(ForeignKey("program_templates.template_id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(120))
    snapshot_json: Mapped[str] = mapped_column(Text)
    published_at: Mapped[str] = mapped_column(String(40))
    __table_args__ = (UniqueConstraint("template_id", "version_no"),)


class ProgramAssignment(Base):
    __tablename__ = "program_assignments"
    assignment_id: Mapped[str] = id_column()
    athlete_id: Mapped[str] = mapped_column(ForeignKey("athletes.athlete_id"), index=True)
    version_id: Mapped[str] = mapped_column(ForeignKey("program_versions.version_id"))
    block_id: Mapped[str] = mapped_column(ForeignKey("training_blocks.block_id"), unique=True)
    start_date: Mapped[str] = mapped_column(String(10))
    active: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[str] = mapped_column(String(40))


class ActualRevision(Base):
    __tablename__ = "actual_revisions"
    revision_id: Mapped[str] = id_column()
    actual_set_id: Mapped[str] = mapped_column(ForeignKey("actual_sets.actual_set_id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    prior_json: Mapped[str | None] = mapped_column(Text)
    new_json: Mapped[str] = mapped_column(Text)
    changed_at: Mapped[str] = mapped_column(String(40))


class RecoveryCheckin(Base):
    __tablename__ = "recovery_checkins"
    checkin_id: Mapped[str] = id_column()
    athlete_id: Mapped[str] = mapped_column(ForeignKey("athletes.athlete_id"), index=True)
    week_id: Mapped[str] = mapped_column(ForeignKey("training_weeks.week_id"), unique=True)
    sleep_hours: Mapped[float | None] = mapped_column(Float)
    readiness: Mapped[int | None] = mapped_column(Integer)
    pain_notes: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str] = mapped_column(String(40))


class RecoveryRevision(Base):
    __tablename__ = "recovery_revisions"
    revision_id: Mapped[str] = id_column()
    checkin_id: Mapped[str] = mapped_column(ForeignKey("recovery_checkins.checkin_id"), index=True)
    actor_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    prior_json: Mapped[str | None] = mapped_column(Text)
    new_json: Mapped[str] = mapped_column(Text)
    changed_at: Mapped[str] = mapped_column(String(40))


class AuditEvent(Base):
    __tablename__ = "audit_events"
    event_id: Mapped[str] = id_column()
    actor_id: Mapped[str] = mapped_column(ForeignKey("accounts.account_id"))
    action: Mapped[str] = mapped_column(String(60))
    target_id: Mapped[str | None] = mapped_column(String(36))
    occurred_at: Mapped[str] = mapped_column(String(40))


def make_engine(url: str | None = None):
    if url is None:
        from strengthos.storage import connect, device_key, private_dir
        root = private_dir()
        def open_workspace():
            if not os.environ.get("STRENGTHOS_DATA_DIR") and not root.exists() and (Path("data") / "strengthos.db").exists():
                raise RuntimeError("Run the local launcher to migrate the existing workspace")
            return connect(root / "strengthos.db", device_key(root))
        from sqlalchemy.pool import QueuePool
        import sqlcipher3
        engine = create_engine("sqlite://", module=sqlcipher3, poolclass=QueuePool, creator=open_workspace, hide_parameters=True)
    else:
        engine = create_engine(url, hide_parameters=True)
    if url is None or url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record):
            cur = dbapi_connection.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=5000")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.close()
    return engine


engine = make_engine(os.environ.get("STRENGTHOS_DATABASE_URL"))
SessionLocal = sessionmaker(engine, expire_on_commit=False)
