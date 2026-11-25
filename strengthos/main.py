from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import uuid
import time
from collections import deque
from threading import Lock
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.formparsers import MultiPartParser
from strengthos.storage import private_dir, backup
from starlette.background import BackgroundTask
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session as DBSession
from argon2 import PasswordHasher

from strengthos.db import (ActualSet, Athlete, Base, DataSource, Exercise, ExercisePrescription,
    ImportJob, MappingProfile, PrescribedSet, RecordRevision, Session, SessionLocal,
    SourceRecord, TrainingBlock, TrainingWeek, engine)
from strengthos.ingestion import MAX_UPLOAD_BYTES, WorkbookLimitError, extract_rows, inspect_workbook, mapping_fingerprint, validate_mapping
from strengthos.metrics import compute
from strengthos.setup import create_coach, normalize_email, credentials

app = FastAPI(title="StrengthOS AI local API", version="0.1.0")
sessions: dict[str, tuple[str, float]] = {}
attempts = deque()
attempt_lock = Lock()
hasher = PasswordHasher()
data_dir = private_dir()
MultiPartParser.spool_max_size = MAX_UPLOAD_BYTES + 1024 * 1024


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse({"detail": "Check the submitted fields."}, status_code=422)


@app.middleware("http")
async def local_boundary(request, call_next):
    host = request.headers.get("host", "")
    origin = request.headers.get("origin")
    writing = request.method not in {"GET", "HEAD", "OPTIONS"}
    if not re.fullmatch(r"(localhost|127\.0\.0\.1)(:[0-9]{1,5})?", host):
        return Response(status_code=400)
    if writing and (origin != "http://" + host and (origin or request.headers.get("sec-fetch-site") or request.url.path.endswith(("/signup", "/login")))):
        return Response(status_code=403)
    if writing:
        length = request.headers.get("content-length", "")
        limit = MAX_UPLOAD_BYTES + 65536 if request.url.path.endswith("/imports/excel") else 1024 * 1024
        if not length.isdecimal() or len(length) > 9 or int(length) > limit:
            return Response(status_code=413)
    response = await call_next(request)
    response.headers.update({
        "Content-Security-Policy": "default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store", "X-Frame-Options": "DENY",
    })
    return response


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    return str(uuid.uuid4())


def db():
    with SessionLocal() as session:
        yield session


def coach(request: Request, x_csrf_token: str | None = Header(None)):
    token = request.cookies.get("strengthos_session")
    entry = sessions.get(token or "")
    if not entry or entry[1] <= time.monotonic():
        sessions.pop(token or "", None)
        raise HTTPException(401, "Coach login required")
    if request.method not in ("GET", "HEAD", "OPTIONS") and not secrets.compare_digest(entry[0], x_csrf_token or ""):
        raise HTTPException(403, "CSRF token required")


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=1, max_length=1024)


class Signup(Login):
    password: str = Field(min_length=12, max_length=1024)


class AthleteInput(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    goal: str | None = Field(default=None, max_length=1000)


class MappingInput(BaseModel):
    import_id: str
    layout_fingerprint: str
    mapping: dict


class MappingDraft(BaseModel):
    mapping: dict


class CommitInput(BaseModel):
    mapping_id: str
    acknowledged_snapshot_hash: str


@app.get("/api/v1/health")
def health():
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1")
        database = "ok"
    except Exception:
        database = "unavailable"
    try:
        ollama_models()
        ollama = "ok"
    except (OSError, ValueError, KeyError, TypeError):
        ollama = "unavailable"
    return {"status": "ok" if database == "ok" else "degraded", "database": database, "ollama": ollama}


def ollama_models():
    with urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as response:
        models = json.load(response)["models"]
    if not isinstance(models, list):
        raise ValueError("Invalid Ollama model list")
    return [{"name": model["name"], "digest": model.get("digest"), "size_bytes": model.get("size")}
            for model in models if isinstance(model, dict) and isinstance(model.get("name"), str)]


@app.get("/api/v1/ollama/models", dependencies=[Depends(coach)])
def list_ollama_models():
    try:
        return ollama_models()
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(503, "Ollama unavailable") from None


@app.post("/api/v1/auth/login")
def login(payload: Login, response: Response):
    email, password_hash = credentials(data_dir)
    if not password_hash or not email:
        raise HTTPException(503, "Set coach email and password with python -m strengthos.setup")
    with attempt_lock:
        stamp = time.monotonic()
        while attempts and attempts[0] <= stamp - 60:
            attempts.popleft()
        if len(attempts) >= 5:
            raise HTTPException(429, "Too many attempts. Try again in one minute.")
        attempts.append(stamp)
    try:
        hasher.verify(password_hash, payload.password)
        valid_email = secrets.compare_digest(email.encode(), normalize_email(payload.email).encode())
    except Exception:
        raise HTTPException(401, "Invalid credentials") from None
    if not valid_email:
        raise HTTPException(401, "Invalid credentials")
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with attempt_lock:
        attempts.clear()
        sessions.clear()
        sessions[token] = (csrf, time.monotonic() + 28800)
    response.set_cookie("strengthos_session", token, httponly=True, samesite="strict", secure=False, max_age=28800)
    return {"csrf_token": csrf}


@app.get("/api/v1/auth/setup-status")
def setup_status():
    email, password_hash = credentials(data_dir)
    return {"signup_available": not email and not password_hash,
            "needs_email_setup": bool(password_hash and not email)}



@app.post("/api/v1/auth/signup", status_code=201)
def signup(payload: Signup):
    try:
        create_coach(data_dir, payload.email, payload.password)
    except FileExistsError:
        raise HTTPException(409, "Coach account already configured") from None
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    return {"ok": True}


@app.post("/api/v1/auth/logout", dependencies=[Depends(coach)])
def logout(request: Request, response: Response):
    sessions.pop(request.cookies.get("strengthos_session", ""), None)
    response.delete_cookie("strengthos_session")
    return {"ok": True}


class BackupRequest(BaseModel):
    passphrase: str = Field(min_length=16, max_length=1024)


@app.post("/api/v1/backups", dependencies=[Depends(coach)])
def download_backup(payload: BackupRequest):
    temp = tempfile.TemporaryDirectory(dir=data_dir)
    path = Path(temp.name) / "workspace.strengthbackup"
    try:
        backup(path, payload.passphrase)
        return FileResponse(path, media_type="application/octet-stream", filename=path.name,
                            background=BackgroundTask(temp.cleanup))
    except Exception:
        temp.cleanup()
        raise HTTPException(500, "Backup could not be verified") from None


@app.get("/api/v1/athletes", dependencies=[Depends(coach)])
def athletes(session: DBSession = Depends(db)):
    return {"items": [{"athlete_id": a.athlete_id, "display_name": a.display_name, "goal": a.goal, "status": a.status} for a in session.scalars(select(Athlete).order_by(Athlete.created_at))]}


@app.post("/api/v1/athletes", status_code=201, dependencies=[Depends(coach)])
def create_athlete(payload: AthleteInput, session: DBSession = Depends(db)):
    a = Athlete(athlete_id=uid(), display_name=payload.display_name.strip(), goal=payload.goal, status="active", created_at=now())
    session.add(a)
    session.commit()
    return {"athlete_id": a.athlete_id, "display_name": a.display_name, "goal": a.goal, "status": a.status}


@app.get("/api/v1/athletes/{athlete_id}", dependencies=[Depends(coach)])
def athlete(athlete_id: str, session: DBSession = Depends(db)):
    a = session.get(Athlete, athlete_id)
    if not a:
        raise HTTPException(404, "Athlete not found")
    return {"athlete_id": a.athlete_id, "display_name": a.display_name, "goal": a.goal, "status": a.status}


@app.get("/api/v1/athletes/{athlete_id}/sources", dependencies=[Depends(coach)])
def athlete_sources(athlete_id: str, session: DBSession = Depends(db)):
    if not session.get(Athlete, athlete_id):
        raise HTTPException(404, "Athlete not found")
    sources = session.scalars(select(DataSource).where(DataSource.athlete_id == athlete_id, DataSource.kind == "excel").order_by(DataSource.created_at))
    return {"items": [{"source_id": source.source_id, "display_name": source.display_name} for source in sources]}


@app.post("/api/v1/imports/excel", dependencies=[Depends(coach)])
async def upload_excel(athlete_id: str = Form(...), file: UploadFile = File(...), source_id: str | None = Form(None), session: DBSession = Depends(db)):
    if not session.get(Athlete, athlete_id):
        raise HTTPException(404, "Athlete not found")
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(422, "Only .xlsx is supported")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        preview = inspect_workbook(data)
    except WorkbookLimitError as exc:
        raise HTTPException(422, str(exc)) from None
    except Exception:
        raise HTTPException(422, "Workbook could not be read. Check the file format and workbook limits.") from None
    if source_id:
        source = session.get(DataSource, source_id)
        if not source or source.athlete_id != athlete_id or source.kind != "excel":
            raise HTTPException(404, "Athlete source not found")
    else:
        source = DataSource(source_id=uid(), athlete_id=athlete_id, kind="excel", display_name=Path(file.filename).name, created_at=now())
        session.add(source)
    fingerprint = hashlib.sha256(data).hexdigest()
    import_id = uid()
    job = ImportJob(import_id=import_id, source_id=source.source_id, source_snapshot_hash=fingerprint,
                    state="queued", preview_json=json.dumps(preview, default=str), snapshot_path="database")
    session.add(job)
    session.flush()
    session.execute(text("INSERT INTO workbook_snapshots VALUES (:id,:content)"), {"id": import_id, "content": data})
    session.commit()
    return {"job_id": import_id, "import_id": import_id, "source_id": source.source_id, "state": "queued"}


@app.get("/api/v1/imports/{import_id}/preview", dependencies=[Depends(coach)])
def import_preview(import_id: str, session: DBSession = Depends(db)):
    job = session.get(ImportJob, import_id)
    if not job:
        raise HTTPException(404, "Import not found")
    result = json.loads(job.preview_json)
    profiles = session.scalars(select(MappingProfile).where(MappingProfile.source_id == job.source_id).order_by(MappingProfile.version.desc())).all()
    if profiles:
        data = _snapshot(session, job)
        for profile in profiles:
            approved = json.loads(profile.mapping_json)
            try:
                validate_mapping(approved, result["sheets"])
                if mapping_fingerprint(data, approved, result["layout_fingerprint"]) != profile.layout_fingerprint:
                    continue
            except (ValueError, KeyError):
                continue
            approved["cell_overrides"] = {}
            approved["actual_status_overrides"] = {}
            result["proposed_mapping"] = approved
            result["reused_mapping_version"] = profile.version
            break
    return {"import_id": import_id, "source_snapshot_hash": job.source_snapshot_hash, **result}


def _snapshot(session: DBSession, job: ImportJob) -> bytes:
    data = session.execute(text("SELECT content FROM workbook_snapshots WHERE import_id=:id"), {"id": job.import_id}).scalar_one_or_none()
    if data is None or hashlib.sha256(data).hexdigest() != job.source_snapshot_hash:
        raise HTTPException(409, "Workbook snapshot unavailable or changed")
    return data


def _review_rows(rows: list[dict], mapping: dict) -> dict:
    issues = []
    corrections = []
    samples = []
    seen: set[str] = set()
    blocking_count = 0
    exercise_labels = sorted({str(row.get("exercise_label")).strip() for row in rows if row.get("exercise_label")})[:500]
    for row in rows:
        row_issues = []
        field_locations = row.get("_field_locations") or ({field: row["_source_columns"][offset]
            for field, offset in (("target_reps", 1), ("target_load", 2), ("target_rpe", 3),
                                  ("actual_reps", 4), ("actual_rpe", 5))} if row.get("_source_columns") else {})
        if field_locations:
            for field, maximum in (("target_reps", None), ("target_load", None),
                                   ("target_rpe", 10), ("actual_reps", None), ("actual_rpe", 10)):
                if field not in field_locations:
                    continue
                value = row.get(field)
                try:
                    number(value, field, 0, maximum)
                except ValueError:
                    location = f"{row['_sheet']}!{field_locations[field]}"
                    row_issues.append({"severity": "blocking", "code": "cell_correction", "location": location,
                                       "message": f"{field.replace('_', ' ').title()} needs a numeric correction or an explicit missing value."})
                    corrections.append({"location": location, "field": field, "raw_value": str(value)[:120]})
            actual = row.get("actual_reps")
            location = f"{row['_sheet']}!{field_locations.get('actual_reps', row['_row'])}"
            if 'actual_reps' in field_locations and actual in (0, 0.0, "0") and not row.get("actual_status"):
                row_issues.append({"severity": "blocking", "code": "zero_actual_status", "location": location,
                                   "message": "Choose failed, skipped or unreported for zero actual reps."})
                corrections.append({"location": location, "field": "actual_status", "raw_value": str(actual)})
        if not row_issues:
            try:
                normalized = _normalize_row(row, mapping, seen)
                if len(samples) < 30:
                    samples.append({"source": f"{row['_sheet']}!{row['_row']}",
                                    "block": normalized["block_label"], "week": normalized["week_label"],
                                    "session": normalized["session_label"], "exercise": normalized["exercise_label"],
                                    "set_index": normalized["set_index"], "side": normalized["side"],
                                    "values": normalized["values"]})
            except ValueError as exc:
                location = f"{row['_sheet']}!{row['_row']}"
                if str(exc) == "Actual values without reps need review" and 'actual_reps' in field_locations:
                    location = f"{row['_sheet']}!{field_locations['actual_reps']}"
                    corrections.append({"location": location, "field": "actual_reps", "raw_value": str(row.get("actual_reps"))})
                row_issues.append({"severity": "blocking", "code": "invalid_set", "location": location,
                                   "message": str(exc)[:200]})
        blocking_count += len(row_issues)
        if len(issues) < 5000:
            issues.extend(row_issues[:5000 - len(issues)])
        if len(corrections) > 5000:
            corrections = corrections[:5000]
    return {"row_count": len(rows), "exercise_labels": exercise_labels, "valid_sample_rows": samples, "blocking_count": blocking_count,
            "issues": issues, "correction_cells": corrections, "issues_truncated": blocking_count > len(issues),
            "can_approve": bool(rows) and blocking_count == 0}


@app.post("/api/v1/imports/{import_id}/mapping-preview", dependencies=[Depends(coach)])
def draft_mapping_preview(import_id: str, payload: MappingDraft, session: DBSession = Depends(db)):
    job = session.get(ImportJob, import_id)
    if not job:
        raise HTTPException(404, "Import not found")
    preview = json.loads(job.preview_json)
    try:
        validate_mapping(payload.mapping, preview["sheets"])
        data = _snapshot(session, job)
        rows = extract_rows(data, payload.mapping)
        fingerprint = mapping_fingerprint(data, payload.mapping, preview["layout_fingerprint"])
    except ValueError as exc:
        raise HTTPException(422, str(exc)[:200]) from None
    return {"source_snapshot_hash": job.source_snapshot_hash, "layout_fingerprint": fingerprint,
            **_review_rows(rows, payload.mapping)}


@app.put("/api/v1/mappings/{mapping_id}", dependencies=[Depends(coach)])
def approve_mapping(mapping_id: str, payload: MappingInput, session: DBSession = Depends(db)):
    job = session.get(ImportJob, payload.import_id)
    if not job:
        raise HTTPException(404, "Import not found")
    preview = json.loads(job.preview_json)
    try:
        validate_mapping(payload.mapping, preview["sheets"])
        data = _snapshot(session, job)
        if payload.layout_fingerprint != mapping_fingerprint(data, payload.mapping, preview["layout_fingerprint"]):
            raise HTTPException(409, "Preview layout changed")
        reviewed = _review_rows(extract_rows(data, payload.mapping), payload.mapping)
        if not reviewed["can_approve"]:
            raise HTTPException(422, f"Mapping has {reviewed['blocking_count']} blocking issues; review cells before approval")
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    version = 1 + max((p.version for p in session.scalars(select(MappingProfile).where(MappingProfile.source_id == job.source_id))), default=0)
    profile = MappingProfile(mapping_id=mapping_id, source_id=job.source_id, version=version,
        layout_fingerprint=payload.layout_fingerprint, mapping_json=json.dumps(payload.mapping), approved_at=now(), approved_by="local_coach")
    session.add(profile)
    session.commit()
    return {"mapping_id": mapping_id, "source_id": job.source_id, "approved_version": version}


def number(value, label, minimum=0, maximum=None):
    if value is None or value == "":
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"Invalid {label}: {value}") from None
    if not math.isfinite(result) or result < minimum or (maximum is not None and result > maximum):
        raise ValueError(f"Out of range {label}: {value}")
    return result


def _normalize_row(row: dict, mapping: dict, seen: set[str]) -> dict:
    if row.get("_set_count_issue"):
        raise ValueError("A row contains more than one set; review its set-count interpretation")
    block_label, week_label, session_label, exercise_label = (str(row.get(k) or "").strip() for k in ("block", "week", "session", "exercise_label"))
    if not all((block_label, week_label, session_label, exercise_label)):
        raise ValueError("Missing block, week, session or exercise")
    week_dates = mapping.get("week_dates", {}).get(week_label)
    week_start = week_end = None
    if week_dates is not None:
        if not isinstance(week_dates, list) or len(week_dates) != 2:
            raise ValueError(f"Invalid week dates for {week_label}")
        try:
            week_start, week_end = (datetime.fromisoformat(d).date().isoformat() for d in week_dates)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid week dates for {week_label}") from None
        if week_end < week_start:
            raise ValueError(f"Week end precedes start for {week_label}")
    try:
        set_index = int(row["set_index"])
    except (TypeError, ValueError):
        raise ValueError("Invalid set index") from None
    if set_index < 1:
        raise ValueError("Set index must be positive")
    side = row.get("side", "both")
    if side not in ("both", "right", "left"):
        raise ValueError("Invalid side")
    set_type = str(row.get("set_type") or "other").lower().replace("-", "")
    if set_type not in ("top", "backoff", "warmup", "other"):
        raise ValueError("Unknown set type")
    canonical_exercise = mapping.get("exercise_aliases", {}).get(exercise_label)
    if not canonical_exercise:
        raise ValueError(f"Exercise alias requires approval: {exercise_label}")
    key = json.dumps([block_label, week_label, session_label, canonical_exercise, set_index, side])
    if key in seen:
        raise ValueError("Duplicate semantic set key")
    factor = 0.45359237 if mapping.get("load_unit", "kg") == "lb" else 1
    target_reps = number(row.get("target_reps"), "target_reps")
    target_load = number(row.get("target_load"), "target_load")
    actual_reps = number(row.get("actual_reps"), "actual_reps")
    actual_load = number(row.get("actual_load"), "actual_load")
    target_rpe = number(row.get("target_rpe"), "target_rpe", 0, 10)
    actual_rpe = number(row.get("actual_rpe"), "actual_rpe", 0, 10)
    ranges = {}
    for field, maximum in (("target_reps", None), ("target_rpe", 10), ("target_rir", None)):
        lower = number(row.get(f"{field}_min"), f"{field}_min", 0, maximum)
        upper = number(row.get(f"{field}_max"), f"{field}_max", 0, maximum)
        if (lower is None) != (upper is None) or (lower is not None and lower > upper):
            raise ValueError(f"Invalid {field} range")
        if lower is not None and row.get(field) is not None:
            raise ValueError(f"Scalar and range {field} both supplied")
        ranges[f"{field}_min"] = lower
        ranges[f"{field}_max"] = upper
    status = str(row.get("actual_status") or "").strip().lower()
    if status and status not in ("completed", "failed", "skipped"):
        raise ValueError("Invalid actual status")
    if not status and any(v is not None for v in (actual_reps, actual_load, actual_rpe)):
        if actual_reps == 0:
            raise ValueError("Zero reps requires failed, skipped or unreported review")
        if mapping.get("schema_version", 1) >= 2 and actual_reps is None:
            raise ValueError("Actual values without reps need review")
        status = "completed"
    if status == "skipped" and any(v is not None for v in (actual_reps, actual_load, actual_rpe)):
        raise ValueError("Skipped set cannot have performance values")
    values = {"target_reps": target_reps, "target_load_kg": target_load * factor if target_load is not None else None,
        "target_rpe": target_rpe, "target_rir": number(row.get("target_rir"), "target_rir"),
        "percent_1rm": number(row.get("percent_1rm"), "percent_1rm", 0, 100),
        "reference_1rm_kg": number(row.get("reference_1rm"), "reference_1rm"),
        "status": status, "reps": actual_reps, "load_kg": actual_load * factor if actual_load is not None else None,
        "actual_rpe": actual_rpe, "actual_rir": number(row.get("actual_rir"), "actual_rir"), **ranges}
    seen.add(key)
    return {"block_label": block_label, "week_label": week_label, "session_label": session_label,
            "exercise_label": exercise_label, "canonical_exercise": canonical_exercise, "set_index": set_index,
            "side": side, "set_type": set_type, "key": key, "week_start": week_start,
            "week_end": week_end, "values": values}


def _commit_rows(session: DBSession, job: ImportJob, profile: MappingProfile, rows: list[dict]):
    if not rows:
        raise ValueError("Mapping produced no training sets")
    mapping = json.loads(profile.mapping_json)
    source = session.get(DataSource, job.source_id)
    changes = 0
    seen = set()
    reviewed_seen: set[str] = set()
    for row in rows:
        _normalize_row(row, mapping, reviewed_seen)
        block_label, week_label, session_label, exercise_label = (str(row.get(k) or "").strip() for k in ("block", "week", "session", "exercise_label"))
        if not all((block_label, week_label, session_label, exercise_label)):
            raise ValueError(f"Missing grouping field at {row['_sheet']}!{row['_row']}")
        week_dates = mapping.get("week_dates", {}).get(week_label)
        week_start = week_end = None
        if week_dates is not None:
            if not isinstance(week_dates, list) or len(week_dates) != 2:
                raise ValueError(f"Invalid week dates for {week_label}")
            try:
                week_start, week_end = (datetime.fromisoformat(d).date().isoformat() for d in week_dates)
            except (ValueError, TypeError):
                raise ValueError(f"Invalid week dates for {week_label}") from None
            if week_end < week_start:
                raise ValueError(f"Week end precedes start for {week_label}")
        try:
            set_index = int(row["set_index"])
        except (TypeError, ValueError):
            raise ValueError(f"Invalid set index at row {row['_row']}") from None
        if set_index < 1:
            raise ValueError("Set index must be positive")
        side = row.get("side", "both")
        if side not in ("both", "right", "left"):
            raise ValueError(f"Invalid side at row {row['_row']}")
        set_type = str(row.get("set_type") or "other").lower().replace("-", "")
        if set_type not in ("top", "backoff", "warmup", "other"):
            raise ValueError(f"Unknown set type at row {row['_row']}")
        canonical_exercise = mapping.get("exercise_aliases", {}).get(exercise_label)
        if not canonical_exercise:
            raise ValueError(f"Exercise alias requires approval: {exercise_label}")
        key = json.dumps([block_label, week_label, session_label, canonical_exercise, set_index, side])
        if key in seen:
            raise ValueError(f"Duplicate semantic set key at row {row['_row']}")
        seen.add(key)
        factor = 0.45359237 if mapping.get("load_unit", "kg") == "lb" else 1
        target_reps = number(row.get("target_reps"), "target_reps")
        target_load = number(row.get("target_load"), "target_load")
        actual_reps = number(row.get("actual_reps"), "actual_reps")
        actual_load = number(row.get("actual_load"), "actual_load")
        target_rpe = number(row.get("target_rpe"), "target_rpe", 0, 10)
        actual_rpe = number(row.get("actual_rpe"), "actual_rpe", 0, 10)
        ranges = {}
        for field, maximum in (("target_reps", None), ("target_rpe", 10), ("target_rir", None)):
            lower = number(row.get(f"{field}_min"), f"{field}_min", 0, maximum)
            upper = number(row.get(f"{field}_max"), f"{field}_max", 0, maximum)
            if (lower is None) != (upper is None) or (lower is not None and lower > upper):
                raise ValueError(f"Invalid {field} range at row {row['_row']}")
            if lower is not None and row.get(field) is not None:
                raise ValueError(f"Scalar and range {field} both supplied at row {row['_row']}")
            ranges[f"{field}_min"] = lower
            ranges[f"{field}_max"] = upper
        status = str(row.get("actual_status") or "").strip().lower()
        if status and status not in ("completed", "failed", "skipped"):
            raise ValueError(f"Invalid actual status at row {row['_row']}")
        if not status and any(v is not None for v in (actual_reps, actual_load, actual_rpe)):
            if actual_reps == 0:
                raise ValueError(f"Zero reps requires an explicit actual status at row {row['_row']}")
            status = "completed"
        if status == "skipped" and any(v is not None for v in (actual_reps, actual_load, actual_rpe)):
            raise ValueError("Skipped set cannot have performance values")
        values = {"target_reps": target_reps, "target_load_kg": target_load * factor if target_load is not None else None,
            "target_rpe": target_rpe, "target_rir": number(row.get("target_rir"), "target_rir"),
            "percent_1rm": number(row.get("percent_1rm"), "percent_1rm", 0, 100),
            "reference_1rm_kg": number(row.get("reference_1rm"), "reference_1rm"),
            "status": status, "reps": actual_reps, "load_kg": actual_load * factor if actual_load is not None else None,
            "actual_rpe": actual_rpe, "actual_rir": number(row.get("actual_rir"), "actual_rir"), **ranges}
        location = f"{row['_sheet']}!{row['_row']}"
        if row.get("_source_columns"):
            location = f"{row['_sheet']}!{row['_source_columns'][0]}:{row['_source_columns'][-1]}"
        content_hash = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()
        record = session.scalar(select(SourceRecord).where(SourceRecord.source_id == job.source_id, SourceRecord.natural_key == key))
        if record and record.content_hash == content_hash:
            continue
        block = session.scalar(select(TrainingBlock).where(TrainingBlock.athlete_id == source.athlete_id, TrainingBlock.label == block_label))
        if not block:
            block = TrainingBlock(block_id=uid(), athlete_id=source.athlete_id, label=block_label, phase="general", start_date=week_start)
            session.add(block); session.flush()
        week = session.scalar(select(TrainingWeek).where(TrainingWeek.block_id == block.block_id, TrainingWeek.week_key == week_label))
        if not week:
            week_match = re.fullmatch(r"week\s*(\d+)", week_label, re.IGNORECASE)
            existing_weeks = session.scalars(select(TrainingWeek).where(TrainingWeek.block_id == block.block_id)).all()
            week_index = int(week_match.group(1)) if week_match else max((item.week_index for item in existing_weeks), default=0) + 1
            week = TrainingWeek(week_id=uid(), block_id=block.block_id, week_key=week_label, week_index=week_index,
                start_date=week_start, end_date=week_end); session.add(week); session.flush()
        elif week_start is not None:
            week.start_date, week.end_date = week_start, week_end
        workout = session.scalar(select(Session).where(Session.week_id == week.week_id, Session.label == session_label))
        if not workout:
            workout = Session(session_id=uid(), week_id=week.week_id, label=session_label, ordinal=len(session.scalars(select(Session).where(Session.week_id == week.week_id)).all()) + 1)
            session.add(workout); session.flush()
        exercise = session.scalar(select(Exercise).where(Exercise.canonical_name == canonical_exercise))
        if not exercise:
            exercise = Exercise(exercise_id=uid(), canonical_name=canonical_exercise, created_at=now()); session.add(exercise); session.flush()
        prescription = session.scalar(select(ExercisePrescription).where(ExercisePrescription.session_id == workout.session_id, ExercisePrescription.exercise_id == exercise.exercise_id))
        if not prescription:
            prescription = ExercisePrescription(prescription_id=uid(), session_id=workout.session_id, exercise_id=exercise.exercise_id,
                source_label=exercise_label, ordinal=len(session.scalars(select(ExercisePrescription).where(ExercisePrescription.session_id == workout.session_id)).all()) + 1)
            session.add(prescription); session.flush()
        planned = session.scalar(select(PrescribedSet).where(PrescribedSet.prescription_id == prescription.prescription_id, PrescribedSet.set_index == set_index, PrescribedSet.side == side))
        if not planned:
            planned = PrescribedSet(prescribed_set_id=uid(), prescription_id=prescription.prescription_id, set_index=set_index, side=side, set_type=set_type)
            session.add(planned); session.flush()
        planned.set_type = set_type
        for field in ("target_reps", "target_reps_min", "target_reps_max", "target_load_kg", "target_rpe", "target_rpe_min", "target_rpe_max", "target_rir", "target_rir_min", "target_rir_max", "percent_1rm", "reference_1rm_kg"):
            setattr(planned, field, values[field])
        performed = session.scalar(select(ActualSet).where(ActualSet.prescribed_set_id == planned.prescribed_set_id))
        if status:
            if not performed:
                performed = ActualSet(actual_set_id=uid(), prescription_id=prescription.prescription_id, prescribed_set_id=planned.prescribed_set_id,
                    set_index=set_index, side=side, status=status, updated_at=now())
                session.add(performed)
            for field in ("status", "reps", "load_kg", "actual_rpe", "actual_rir"):
                setattr(performed, field, values[field])
            performed.updated_at = now()
        elif performed:
            session.delete(performed)
        if record:
            session.add(RecordRevision(revision_id=uid(), source_record_id=record.source_record_id, revision_no=record.current_revision + 1,
                prior_json=record.raw_json, new_json=json.dumps(row, default=str), changed_at=now(), reason="reimport"))
            record.current_revision += 1
            record.content_hash = content_hash
            record.raw_json = json.dumps(row, default=str)
            record.cell_range = location
            record.import_id = job.import_id
        else:
            record = SourceRecord(source_record_id=uid(), source_id=job.source_id, import_id=job.import_id, mapping_id=profile.mapping_id,
                natural_key=key, content_hash=content_hash, sheet_name=row["_sheet"], cell_range=location,
                raw_json=json.dumps(row, default=str), canonical_type="prescribed_set", canonical_id=planned.prescribed_set_id)
            session.add(record)
        changes += 1
    existing_keys = set(session.scalars(select(SourceRecord.natural_key).where(SourceRecord.source_id == job.source_id)))
    missing_keys = existing_keys - seen
    if missing_keys:
        raise ValueError(f"Source contains {len(missing_keys)} previously imported sets that are now absent; review deletion before commit")
    return changes


@app.post("/api/v1/imports/{import_id}/commit", dependencies=[Depends(coach)])
def commit_import(import_id: str, payload: CommitInput, session: DBSession = Depends(db)):
    job = session.get(ImportJob, import_id)
    profile = session.get(MappingProfile, payload.mapping_id)
    if not job or not profile or profile.source_id != job.source_id:
        raise HTTPException(404, "Import or mapping not found")
    if payload.acknowledged_snapshot_hash != job.source_snapshot_hash:
        raise HTTPException(409, "Snapshot hash mismatch")
    data = _snapshot(session, job)
    preview = inspect_workbook(data)
    approved = json.loads(profile.mapping_json)
    if mapping_fingerprint(data, approved, preview["layout_fingerprint"]) != profile.layout_fingerprint:
        raise HTTPException(409, "Layout drift requires review")
    try:
        rows = extract_rows(data, approved)
        if not approved.get("exercise_aliases"):
            raise ValueError("Exercise aliases require approval")
        changes = _commit_rows(session, job, profile, rows)
        job.state = "completed"
        job.mapping_id = profile.mapping_id
        job.finished_at = now()
        session.commit()
    except ValueError as exc:
        session.rollback()
        raise HTTPException(422, str(exc)) from None
    return {"job_id": job.import_id, "state": "completed", "changed_records": changes}


@app.get("/api/v1/athletes/{athlete_id}/analytics", dependencies=[Depends(coach)])
def analytics(athlete_id: str, session: DBSession = Depends(db)):
    if not session.get(Athlete, athlete_id):
        raise HTTPException(404, "Athlete not found")
    query = select(PrescribedSet, ActualSet, SourceRecord, ExercisePrescription.exercise_id).join(ExercisePrescription, PrescribedSet.prescription_id == ExercisePrescription.prescription_id).join(Session, ExercisePrescription.session_id == Session.session_id).join(TrainingWeek, Session.week_id == TrainingWeek.week_id).join(TrainingBlock, TrainingWeek.block_id == TrainingBlock.block_id).outerjoin(ActualSet, ActualSet.prescribed_set_id == PrescribedSet.prescribed_set_id).outerjoin(SourceRecord, SourceRecord.canonical_id == PrescribedSet.prescribed_set_id).where(TrainingBlock.athlete_id == athlete_id)
    rows = [{"id": p.prescribed_set_id, "exercise_id": exercise_id, "set_type": p.set_type, "side": p.side,
        "target_reps": p.target_reps, "target_reps_min": p.target_reps_min, "target_reps_max": p.target_reps_max,
        "target_rpe": p.target_rpe, "target_rpe_min": p.target_rpe_min, "target_rpe_max": p.target_rpe_max,
        "target_rir": p.target_rir, "target_rir_min": p.target_rir_min, "target_rir_max": p.target_rir_max,
        "status": a.status if a else None, "reps": a.reps if a else None,
        "load_kg": a.load_kg if a else None, "actual_rpe": a.actual_rpe if a else None,
        "source": {"sheet": s.sheet_name, "cell_range": s.cell_range} if s else None} for p, a, s, exercise_id in session.execute(query)]
    return {"athlete_id": athlete_id, "metrics": compute(rows), "sets": rows}


@app.get("/api/v1/jobs/{job_id}", dependencies=[Depends(coach)])
def get_job(job_id: str, session: DBSession = Depends(db)):
    job = session.get(ImportJob, job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return {"job_id": job_id, "state": job.state, "error_code": job.error_code}


dist = Path("dist")
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
    @app.get("/{path:path}")
    def frontend(path: str):
        if path not in {"", "sign-in", "sign-up"}:
            raise HTTPException(404, "Page not found")
        return FileResponse(dist / "index.html")
