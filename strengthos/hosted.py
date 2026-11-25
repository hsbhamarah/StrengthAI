"""Public, same-origin coach and client portal. Set STRENGTHOS_DATABASE_URL before import."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import struct
import time
from contextlib import asynccontextmanager, suppress
from datetime import date, datetime, timedelta, timezone
from getpass import getpass
from pathlib import Path
from uuid import uuid4

from argon2 import PasswordHasher
from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session as DBSession

from strengthos.db import (Account, ActualRevision, ActualSet, Athlete, AuditEvent, AuthSession,
    ClientInvite, Exercise, ExercisePrescription, PrescribedSet, ProgramAssignment, ProgramTemplate,
    ProgramVersion, RecoveryCheckin, RecoveryRevision, Session, SessionLocal, TemplateImport, TrainingBlock,
    TrainingWeek)
from strengthos.ingestion import MAX_UPLOAD_BYTES, extract_rows, inspect_workbook, validate_mapping
from strengthos.metrics import compute

if not os.environ.get("STRENGTHOS_DATABASE_URL"):
    raise RuntimeError("STRENGTHOS_DATABASE_URL is required for the hosted portal")

ORIGIN = os.environ.get("STRENGTHOS_PUBLIC_ORIGIN", "").rstrip("/")
DEV = ORIGIN.startswith("http://127.0.0.1:") or ORIGIN.startswith("http://localhost:")
if not ORIGIN.startswith("https://") and not DEV:
    raise RuntimeError("STRENGTHOS_PUBLIC_ORIGIN must use HTTPS except for loopback development")

def purge_expired_imports():
    with SessionLocal.begin() as session:
        for item in session.scalars(select(TemplateImport).where(TemplateImport.expires_at <= stamp(),
                                                                TemplateImport.content.is_not(None))):
            item.content = None


@asynccontextmanager
async def lifespan(_app):
    purge_expired_imports()
    async def hourly_cleanup():
        while True:
            await asyncio.sleep(3600)
            purge_expired_imports()
    task = asyncio.create_task(hourly_cleanup())
    try:
        yield
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="StrengthOS client portal", version="0.2.0", docs_url=None, redoc_url=None, lifespan=lifespan)
hasher = PasswordHasher()
COOKIE = "__Host-strengthos"
SESSION_COOKIE = "strengthos_dev" if DEV else COOKIE


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def uid() -> str:
    return str(uuid4())


def db():
    with SessionLocal() as session:
        yield session


def audit(session: DBSession, actor: Account, action: str, target: str | None = None):
    session.add(AuditEvent(event_id=uid(), actor_id=actor.account_id, action=action,
                           target_id=target, occurred_at=stamp()))


def totp(secret: str, moment: int | None = None) -> str:
    key = base64.b32decode(secret, casefold=True)
    counter = struct.pack(">Q", (moment or int(time.time())) // 30)
    raw = hmac.new(key, counter, hashlib.sha1).digest()
    offset = raw[-1] & 15
    value = struct.unpack(">I", raw[offset:offset + 4])[0] & 0x7fffffff
    return f"{value % 1000000:06d}"


def verify_mfa(account: Account, code: str) -> bool:
    if account.mfa_secret and len(code) == 6 and code.isdecimal():
        current = int(time.time())
        if any(secrets.compare_digest(totp(account.mfa_secret, current + delta), code)
               for delta in (-30, 0, 30)):
            return True
    hashes = json.loads(account.recovery_hashes_json or "[]")
    candidate = digest(code.strip().upper())
    if candidate in hashes:
        hashes.remove(candidate)
        account.recovery_hashes_json = json.dumps(hashes)
        return True
    return False


@app.middleware("http")
async def public_boundary(request: Request, call_next):
    expected_host = ORIGIN.split("://", 1)[1]
    if request.headers.get("host", "").lower() != expected_host.lower():
        return Response(status_code=400)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("origin") != ORIGIN:
            return Response(status_code=403)
        length = request.headers.get("content-length", "")
        if not length.isdecimal() or int(length) > 11 * 1024 * 1024:
            return Response(status_code=413)
    response = await call_next(request)
    response.headers.update({
        "Content-Security-Policy": "default-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
        "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
        "Cache-Control": "no-store", "X-Frame-Options": "DENY",
    })
    if not DEV:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


def current(request: Request, x_csrf_token: str | None = Header(None), session: DBSession = Depends(db)) -> Account:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(401, "Sign in required")
    auth = session.scalar(select(AuthSession).where(AuthSession.token_hash == digest(token),
                                                   AuthSession.revoked_at.is_(None)))
    now = stamp()
    if not auth or auth.expires_at <= now or (datetime.now(timezone.utc) - datetime.fromisoformat(auth.touched_at)) > timedelta(hours=1):
        raise HTTPException(401, "Session expired")
    account = session.get(Account, auth.account_id)
    if not account or account.disabled_at:
        raise HTTPException(401, "Account inactive")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and (not x_csrf_token or not secrets.compare_digest(auth.csrf_hash, digest(x_csrf_token))):
        raise HTTPException(403, "CSRF token required")
    if (datetime.now(timezone.utc) - datetime.fromisoformat(auth.touched_at)) > timedelta(minutes=5):
        auth.touched_at = now
        session.commit()
    return account


def coach(account: Account = Depends(current)) -> Account:
    if account.role != "coach":
        raise HTTPException(403, "Coach access required")
    return account


def client(account: Account = Depends(current)) -> Account:
    if account.role != "client":
        raise HTTPException(403, "Client access required")
    return account


def own_athlete(session: DBSession, account: Account, athlete_id: str):
    if account.role != "coach" and account.athlete_id != athlete_id:
        raise HTTPException(404, "Athlete not found")
    athlete = session.get(Athlete, athlete_id)
    if not athlete:
        raise HTTPException(404, "Athlete not found")
    return athlete


class Login(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=1024)
    mfa_code: str = ""


class InviteAcceptance(BaseModel):
    token: str = Field(min_length=40, max_length=200)
    password: str = Field(min_length=12, max_length=1024)


class InviteInput(BaseModel):
    email: str = Field(min_length=3, max_length=254)


class AthleteInput(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    goal: str | None = Field(default=None, max_length=1000)


def email_key(value: str) -> str:
    email = value.strip().casefold()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(422, "Invalid email")
    return email


@app.get("/api/v1/health")
def health(session: DBSession = Depends(db)):
    session.execute(select(func.count()).select_from(Account)).scalar()
    return {"status": "ok"}


@app.post("/api/v1/auth/login")
def login(payload: Login, response: Response, request: Request, session: DBSession = Depends(db)):
    # shortcut: one worker handles login throttling; use a shared store when scaling beyond one VM.
    key = "email:" + digest(email_key(payload.email))
    ip_key = "ip:" + (request.client.host if request.client else "unknown")
    now_monotonic = time.monotonic()
    for old_key in list(login_attempts):
        login_attempts[old_key] = [t for t in login_attempts[old_key] if t > now_monotonic - 300]
        if not login_attempts[old_key]:
            del login_attempts[old_key]
    if len(login_attempts.get(key, [])) >= 8 or len(login_attempts.get(ip_key, [])) >= 30:
        raise HTTPException(429, "Try again later")
    login_attempts.setdefault(key, []).append(now_monotonic)
    login_attempts.setdefault(ip_key, []).append(now_monotonic)
    account = session.scalar(select(Account).where(Account.email == email_key(payload.email)))
    try:
        valid = bool(account and not account.disabled_at and hasher.verify(account.password_hash, payload.password))
    except Exception:
        valid = False
    if not valid or (account.role == "coach" and not verify_mfa(account, payload.mfa_code)):
        raise HTTPException(401, "Invalid credentials")
    login_attempts.pop(key, None)
    if account.role == "coach":
        for prior in session.scalars(select(AuthSession).where(AuthSession.account_id == account.account_id,
                                                              AuthSession.revoked_at.is_(None))):
            prior.revoked_at = stamp()
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    session.add(AuthSession(session_id=uid(), account_id=account.account_id, token_hash=digest(token),
                            csrf_hash=digest(csrf), created_at=stamp(), touched_at=stamp(),
                            expires_at=(datetime.now(timezone.utc) + timedelta(hours=8)).isoformat()))
    audit(session, account, "login")
    session.commit()
    response.set_cookie(SESSION_COOKIE, token, httponly=True, secure=not DEV,
                        samesite="strict", path="/", max_age=28800)
    return {"role": account.role, "csrf_token": csrf, "athlete_id": account.athlete_id}


login_attempts: dict[str, list[float]] = {}


@app.get("/api/v1/auth/me")
def me(account: Account = Depends(current)):
    return {"role": account.role, "email": account.email, "athlete_id": account.athlete_id}


@app.get("/api/v1/auth/sessions")
def list_sessions(request: Request, account: Account = Depends(current), session: DBSession = Depends(db)):
    current_hash = digest(request.cookies[SESSION_COOKIE])
    return {"items": [{"session_id": item.session_id, "created_at": item.created_at,
                       "touched_at": item.touched_at, "current": item.token_hash == current_hash}
                      for item in session.scalars(select(AuthSession).where(
                          AuthSession.account_id == account.account_id,
                          AuthSession.revoked_at.is_(None)).order_by(AuthSession.created_at.desc()))]}


@app.post("/api/v1/auth/sessions/revoke-others")
def revoke_other_sessions(request: Request, account: Account = Depends(current), session: DBSession = Depends(db)):
    current_hash = digest(request.cookies[SESSION_COOKIE])
    for item in session.scalars(select(AuthSession).where(AuthSession.account_id == account.account_id,
                                                       AuthSession.revoked_at.is_(None))):
        if item.token_hash != current_hash:
            item.revoked_at = stamp()
    audit(session, account, "other_sessions_revoked")
    session.commit()
    return {"ok": True}


@app.post("/api/v1/auth/logout")
def logout(request: Request, response: Response, account: Account = Depends(current), session: DBSession = Depends(db)):
    auth = session.scalar(select(AuthSession).where(AuthSession.token_hash == digest(request.cookies[SESSION_COOKIE])))
    auth.revoked_at = stamp()
    audit(session, account, "logout")
    session.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.headers["Clear-Site-Data"] = '"cache", "storage"'
    return {"ok": True}


@app.post("/api/v1/auth/invites/accept", status_code=201)
def accept_invite(payload: InviteAcceptance, session: DBSession = Depends(db)):
    invite = session.scalar(select(ClientInvite).where(ClientInvite.token_hash == digest(payload.token)))
    if not invite or invite.used_at or invite.revoked_at or invite.expires_at <= stamp():
        raise HTTPException(404, "Invite expired or unavailable")
    existing = session.scalar(select(Account).where(Account.email == invite.email))
    if existing and existing.athlete_id != invite.athlete_id:
        raise HTTPException(409, "Account already exists")
    if existing:
        existing.password_hash = hasher.hash(payload.password)
        existing.disabled_at = None
        for prior in session.scalars(select(AuthSession).where(AuthSession.account_id == existing.account_id,
                                                              AuthSession.revoked_at.is_(None))):
            prior.revoked_at = stamp()
        account = existing
    else:
        account = Account(account_id=uid(), athlete_id=invite.athlete_id, role="client",
                          email=invite.email, password_hash=hasher.hash(payload.password), created_at=stamp())
        session.add(account)
    invite.used_at = stamp()
    audit(session, account, "invite_accepted", invite.invite_id)
    session.commit()
    return {"ok": True}


@app.get("/api/v1/athletes", dependencies=[Depends(coach)])
def athletes(session: DBSession = Depends(db)):
    return {"items": [{"athlete_id": a.athlete_id, "display_name": a.display_name, "goal": a.goal,
                       "status": a.status} for a in session.scalars(select(Athlete).order_by(Athlete.created_at))]}


@app.post("/api/v1/athletes", status_code=201)
def create_athlete(payload: AthleteInput, actor: Account = Depends(coach), session: DBSession = Depends(db)):
    athlete = Athlete(athlete_id=uid(), display_name=payload.display_name.strip(), goal=payload.goal,
                      status="active", created_at=stamp())
    session.add(athlete)
    audit(session, actor, "athlete_created", athlete.athlete_id)
    session.commit()
    return {"athlete_id": athlete.athlete_id, "display_name": athlete.display_name, "goal": athlete.goal, "status": athlete.status}


@app.post("/api/v1/athletes/{athlete_id}/invites", status_code=201)
def invite_client(athlete_id: str, payload: InviteInput, actor: Account = Depends(coach), session: DBSession = Depends(db)):
    own_athlete(session, actor, athlete_id)
    address = email_key(payload.email)
    existing = session.scalar(select(Account).where(Account.email == address))
    if existing and existing.athlete_id != athlete_id:
        raise HTTPException(409, "Email belongs to another account")
    for old in session.scalars(select(ClientInvite).where(ClientInvite.athlete_id == athlete_id,
                                                          ClientInvite.used_at.is_(None), ClientInvite.revoked_at.is_(None))):
        old.revoked_at = stamp()
    token = secrets.token_urlsafe(32)
    invite = ClientInvite(invite_id=uid(), athlete_id=athlete_id, email=address, token_hash=digest(token),
                          created_at=stamp(), expires_at=(datetime.now(timezone.utc) + timedelta(hours=72)).isoformat())
    session.add(invite)
    audit(session, actor, "invite_created", invite.invite_id)
    session.commit()
    return {"invite_id": invite.invite_id, "url": ORIGIN + "/invite?token=" + token,
            "expires_at": invite.expires_at}


@app.post("/api/v1/athletes/{athlete_id}/deactivate")
def deactivate_client(athlete_id: str, actor: Account = Depends(coach), session: DBSession = Depends(db)):
    own_athlete(session, actor, athlete_id)
    for invite in session.scalars(select(ClientInvite).where(ClientInvite.athlete_id == athlete_id,
                                                               ClientInvite.used_at.is_(None),
                                                               ClientInvite.revoked_at.is_(None))):
        invite.revoked_at = stamp()
    account = session.scalar(select(Account).where(Account.athlete_id == athlete_id))
    if account:
        account.disabled_at = stamp()
        for auth in session.scalars(select(AuthSession).where(AuthSession.account_id == account.account_id,
                                                             AuthSession.revoked_at.is_(None))):
            auth.revoked_at = stamp()
    audit(session, actor, "client_deactivated", athlete_id)
    session.commit()
    return {"ok": True}


@app.post("/api/v1/invites/{invite_id}/revoke")
def revoke_invite(invite_id: str, actor: Account = Depends(coach), session: DBSession = Depends(db)):
    invite = session.get(ClientInvite, invite_id)
    if not invite:
        raise HTTPException(404, "Invite not found")
    invite.revoked_at = stamp()
    audit(session, actor, "invite_revoked", invite_id)
    session.commit()
    return {"ok": True}


class SetSpec(BaseModel):
    set_index: int | None = Field(default=None, ge=1, le=1000)
    side: str = Field(default="both", pattern="^(both|left|right)$")
    set_type: str = Field(default="working", pattern="^(working|top|backoff|warmup|other)$")
    target_reps: float | None = Field(default=None, ge=0, le=1000)
    target_reps_min: float | None = Field(default=None, ge=0, le=1000)
    target_reps_max: float | None = Field(default=None, ge=0, le=1000)
    target_load_kg: float | None = Field(default=None, ge=0, le=2000)
    target_rpe: float | None = Field(default=None, ge=0, le=10)
    target_rpe_min: float | None = Field(default=None, ge=0, le=10)
    target_rpe_max: float | None = Field(default=None, ge=0, le=10)
    target_rir: float | None = Field(default=None, ge=0, le=100)
    target_rir_min: float | None = Field(default=None, ge=0, le=100)
    target_rir_max: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def ranges(self):
        if any(not math.isfinite(value) for value in self.model_dump().values() if isinstance(value, float)):
            raise ValueError("Targets must be finite")
        for field in ("target_reps", "target_rpe", "target_rir"):
            scalar, lower, upper = (getattr(self, name) for name in (field, field + "_min", field + "_max"))
            if (lower is None) != (upper is None) or (lower is not None and (lower > upper or scalar is not None)):
                raise ValueError("Invalid target range")
        return self


class ExerciseSpec(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)
    sets: list[SetSpec] = Field(default_factory=list, max_length=30)


class SessionSpec(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    day_offset: int = Field(ge=0, le=6)
    exercises: list[ExerciseSpec] = Field(default_factory=list, max_length=40)


class WeekSpec(BaseModel):
    sessions: list[SessionSpec] = Field(default_factory=list, max_length=14)


class ProgramSpec(BaseModel):
    weeks: list[WeekSpec] = Field(default_factory=list, max_length=52)

    @model_validator(mode="after")
    def validate_size(self):
        if sum(len(exercise.sets) for week in self.weeks for workout in week.sessions
               for exercise in workout.exercises) > 2000:
            raise ValueError("Program exceeds 2,000 sets")
        return self


class TemplateInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    program: ProgramSpec


class AssignmentInput(BaseModel):
    athlete_ids: list[str] = Field(min_length=1, max_length=100)
    start_date: date


class ImportMapping(BaseModel):
    mapping: dict


class ImportApproval(ImportMapping):
    acknowledged_hash: str = Field(min_length=64, max_length=64)
    mapping_hash: str = Field(min_length=64, max_length=64)
    approve: bool


def mapping_digest(mapping: dict) -> str:
    return hashlib.sha256(json.dumps(mapping, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def import_snapshot(session: DBSession, import_id: str):
    item = session.get(TemplateImport, import_id)
    if not item or not item.content or item.expires_at <= stamp():
        if item and item.expires_at <= stamp() and item.content:
            item.content = None
            session.commit()
        raise HTTPException(404, "Import expired or unavailable")
    return item


def import_programs(data: bytes, mapping: dict):
    inspection = inspect_workbook(data)
    validate_mapping(mapping, inspection["sheets"])
    rows = extract_rows(data, mapping)
    if not rows:
        raise ValueError("No sets found in this mapping")
    blocks: dict[str, dict[str, dict[str, dict[str, list[dict]]]]] = {}
    seen: set[tuple] = set()
    samples = []
    for row in rows:
        if row.get("_set_count_issue"):
            raise ValueError("A source row contains an ambiguous set count")
        block, week, workout, exercise = (str(row.get(key) or "").strip() for key in
                                          ("block", "week", "session", "exercise_label"))
        if not all((block, week, workout, exercise)):
            raise ValueError("Block, week, session and exercise are required")
        alias = str(mapping.get("exercise_aliases", {}).get(exercise) or "").strip()
        if not alias:
            raise ValueError(f"Approve an exercise alias for {exercise}")
        try:
            set_index = int(row["set_index"])
        except (KeyError, TypeError, ValueError):
            raise ValueError("Set index must be a positive number") from None
        side = row.get("side") or "both"
        key = (block, week, workout, alias, set_index, side)
        if key in seen:
            raise ValueError("Duplicate block, week, session, exercise, set and side")
        seen.add(key)
        factor = 0.45359237 if mapping.get("load_unit", "kg") == "lb" else 1
        def numeric(field: str):
            value = row.get(field)
            if value is None or value == "":
                return None
            try:
                result = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"Invalid {field} at {row.get('_sheet', 'workbook')} row {row.get('_row', '?')}") from None
            if not math.isfinite(result):
                raise ValueError(f"Invalid {field} at {row.get('_sheet', 'workbook')} row {row.get('_row', '?')}")
            return result
        set_spec = SetSpec(set_index=set_index, side=side, set_type=str(row.get("set_type") or "other").lower().replace("-", ""),
            target_reps=numeric("target_reps"), target_reps_min=numeric("target_reps_min"),
            target_reps_max=numeric("target_reps_max"), target_load_kg=(numeric("target_load") or 0) * factor if numeric("target_load") is not None else None,
            target_rpe=numeric("target_rpe"), target_rpe_min=numeric("target_rpe_min"),
            target_rpe_max=numeric("target_rpe_max"), target_rir=numeric("target_rir"),
            target_rir_min=numeric("target_rir_min"), target_rir_max=numeric("target_rir_max"))
        blocks.setdefault(block, {}).setdefault(week, {}).setdefault(workout, {}).setdefault(alias, []).append(set_spec.model_dump())
        if len(samples) < 12:
            samples.append({"block": block, "week": week, "session": workout, "exercise": alias,
                            "set_index": set_index, "side": side, "target_reps": set_spec.target_reps})
    programs = {}
    for block, weeks in blocks.items():
        week_specs = []
        for workouts in weeks.values():
            sessions = []
            for ordinal, (label, exercises) in enumerate(workouts.items()):
                sessions.append(SessionSpec(label=label, day_offset=min(ordinal, 6),
                    exercises=[ExerciseSpec(name=name, sets=[SetSpec(**item) for item in sets])
                               for name, sets in exercises.items()]))
            week_specs.append(WeekSpec(sessions=sessions))
        programs[block] = ProgramSpec(weeks=week_specs)
    return programs, samples, len(rows)


@app.post("/api/v1/template-imports", status_code=201)
async def upload_template(file: UploadFile = File(...), actor: Account = Depends(coach), session: DBSession = Depends(db)):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(422, "Upload an .xlsx workbook")
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        inspection = inspect_workbook(data)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from None
    for expired in session.scalars(select(TemplateImport).where(TemplateImport.expires_at <= stamp(),
                                                               TemplateImport.content.is_not(None))):
        expired.content = None
    outstanding = session.scalar(select(func.count()).select_from(TemplateImport).where(
        TemplateImport.content.is_not(None), TemplateImport.expires_at > stamp()))
    if outstanding >= 3:
        raise HTTPException(429, "Finish or wait for an existing workbook preview")
    item = TemplateImport(import_id=uid(), filename=Path(file.filename).name[:255],
                          content_hash=hashlib.sha256(data).hexdigest(), content=data, created_at=stamp(),
                          expires_at=(datetime.now(timezone.utc) + timedelta(hours=24)).isoformat())
    session.add(item)
    audit(session, actor, "workbook_uploaded", item.import_id)
    session.commit()
    return {"import_id": item.import_id, "content_hash": item.content_hash,
            "sheets": inspection["sheets"], "proposed_mapping": inspection.get("proposed_mapping"),
            "sample_rows": inspection.get("sample_rows", []), "issues": inspection.get("issues", [])}


@app.post("/api/v1/template-imports/{import_id}/preview")
def preview_template(import_id: str, payload: ImportMapping, actor: Account = Depends(coach),
                     session: DBSession = Depends(db)):
    item = import_snapshot(session, import_id)
    try:
        programs, samples, count = import_programs(item.content, payload.mapping)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from None
    item.preview_mapping_hash = mapping_digest(payload.mapping)
    item.previewed_at = stamp()
    session.commit()
    return {"row_count": count, "blocks": list(programs), "sample_sets": samples,
            "mapping_hash": mapping_digest(payload.mapping), "content_hash": item.content_hash,
            "note": "Imported actuals are omitted. Review session days and targets before publishing."}


@app.post("/api/v1/template-imports/{import_id}/approve", status_code=201)
def approve_template_import(import_id: str, payload: ImportApproval, actor: Account = Depends(coach),
                            session: DBSession = Depends(db)):
    item = import_snapshot(session, import_id)
    if (not payload.approve or payload.acknowledged_hash != item.content_hash or
            payload.mapping_hash != mapping_digest(payload.mapping) or
            item.preview_mapping_hash != payload.mapping_hash or not item.previewed_at):
        raise HTTPException(422, "Preview and workbook hash must be acknowledged")
    try:
        programs, _, _ = import_programs(item.content, payload.mapping)
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from None
    made = []
    for block, program in programs.items():
        template = ProgramTemplate(template_id=uid(), name=block[:120], draft_json=program.model_dump_json(),
                                   created_at=stamp(), updated_at=stamp())
        session.add(template)
        made.append(template.template_id)
        audit(session, actor, "workbook_draft_approved", template.template_id)
    item.content = None
    item.committed_at = stamp()
    session.commit()
    return {"template_ids": made}


def template_json(template: ProgramTemplate):
    return {"template_id": template.template_id, "name": template.name,
            "program": json.loads(template.draft_json), "updated_at": template.updated_at}


@app.get("/api/v1/templates", dependencies=[Depends(coach)])
def list_templates(session: DBSession = Depends(db)):
    return {"items": [template_json(t) for t in session.scalars(select(ProgramTemplate).order_by(ProgramTemplate.updated_at.desc()))]}


@app.post("/api/v1/templates", status_code=201)
def create_template(payload: TemplateInput, actor: Account = Depends(coach), session: DBSession = Depends(db)):
    item = ProgramTemplate(template_id=uid(), name=payload.name.strip(), draft_json=payload.program.model_dump_json(),
                           created_at=stamp(), updated_at=stamp())
    session.add(item)
    audit(session, actor, "template_created", item.template_id)
    session.commit()
    return template_json(item)


@app.put("/api/v1/templates/{template_id}")
def edit_template(template_id: str, payload: TemplateInput, actor: Account = Depends(coach), session: DBSession = Depends(db)):
    item = session.get(ProgramTemplate, template_id)
    if not item:
        raise HTTPException(404, "Template not found")
    item.name = payload.name.strip()
    item.draft_json = payload.program.model_dump_json()
    item.updated_at = stamp()
    audit(session, actor, "template_edited", template_id)
    session.commit()
    return template_json(item)


@app.post("/api/v1/templates/{template_id}/clone", status_code=201)
def clone_template(template_id: str, actor: Account = Depends(coach), session: DBSession = Depends(db)):
    original = session.get(ProgramTemplate, template_id)
    if not original:
        raise HTTPException(404, "Template not found")
    item = ProgramTemplate(template_id=uid(), name=original.name + " copy", draft_json=original.draft_json,
                           created_at=stamp(), updated_at=stamp())
    session.add(item)
    audit(session, actor, "template_cloned", item.template_id)
    session.commit()
    return template_json(item)


def publishable(program: ProgramSpec):
    if not program.weeks or any(not week.sessions for week in program.weeks):
        raise HTTPException(422, "Every published week needs a session")
    if any(not workout.exercises or any(not exercise.sets for exercise in workout.exercises)
           for week in program.weeks for workout in week.sessions):
        raise HTTPException(422, "Every session needs an exercise and every exercise needs a set")
    for week in program.weeks:
        for workout in week.sessions:
            for exercise in workout.exercises:
                keys = [(item.set_index or index, item.side) for index, item in enumerate(exercise.sets, 1)]
                if len(keys) != len(set(keys)):
                    raise HTTPException(422, "Duplicate set index and side")


@app.post("/api/v1/templates/{template_id}/publish", status_code=201)
def publish(template_id: str, actor: Account = Depends(coach), session: DBSession = Depends(db)):
    item = session.get(ProgramTemplate, template_id)
    if not item:
        raise HTTPException(404, "Template not found")
    program = ProgramSpec.model_validate_json(item.draft_json)
    publishable(program)
    number = (session.scalar(select(func.max(ProgramVersion.version_no)).where(ProgramVersion.template_id == template_id)) or 0) + 1
    version = ProgramVersion(version_id=uid(), template_id=template_id, version_no=number,
                             name=item.name, snapshot_json=program.model_dump_json(), published_at=stamp())
    session.add(version)
    audit(session, actor, "program_published", version.version_id)
    session.commit()
    return {"version_id": version.version_id, "template_id": template_id, "version_no": number}


@app.get("/api/v1/templates/{template_id}/versions", dependencies=[Depends(coach)])
def versions(template_id: str, session: DBSession = Depends(db)):
    if not session.get(ProgramTemplate, template_id):
        raise HTTPException(404, "Template not found")
    return {"items": [{"version_id": v.version_id, "version_no": v.version_no, "published_at": v.published_at}
                      for v in session.scalars(select(ProgramVersion).where(ProgramVersion.template_id == template_id).order_by(ProgramVersion.version_no.desc()))]}


def materialize(session: DBSession, version: ProgramVersion, athlete_id: str, start: date):
    program = ProgramSpec.model_validate_json(version.snapshot_json)
    block = TrainingBlock(block_id=uid(), athlete_id=athlete_id, label=f"Program {version.version_no}",
                          phase="published", start_date=start.isoformat(),
                          end_date=(start + timedelta(days=7 * len(program.weeks) - 1)).isoformat())
    session.add(block)
    session.flush()
    assignment = ProgramAssignment(assignment_id=uid(), athlete_id=athlete_id, version_id=version.version_id,
                                   block_id=block.block_id, start_date=start.isoformat(), active=1, created_at=stamp())
    session.add(assignment)
    for index, week_spec in enumerate(program.weeks):
        first = start + timedelta(days=7 * index)
        week = TrainingWeek(week_id=uid(), block_id=block.block_id, week_key=f"Week {index + 1}",
                            week_index=index + 1, start_date=first.isoformat(),
                            end_date=(first + timedelta(days=6)).isoformat(),
                            checkin_due_at=(datetime.combine(first + timedelta(days=6), datetime.min.time(), timezone.utc) + timedelta(days=1)).isoformat())
        session.add(week)
        session.flush()
        for ordinal, workout_spec in enumerate(week_spec.sessions, 1):
            workout = Session(session_id=uid(), week_id=week.week_id, label=workout_spec.label,
                              ordinal=ordinal, session_date=(first + timedelta(days=workout_spec.day_offset)).isoformat())
            session.add(workout)
            session.flush()
            for exercise_ordinal, exercise_spec in enumerate(workout_spec.exercises, 1):
                exercise = session.scalar(select(Exercise).where(Exercise.canonical_name == exercise_spec.name.strip()))
                if not exercise:
                    exercise = Exercise(exercise_id=uid(), canonical_name=exercise_spec.name.strip(), created_at=stamp())
                    session.add(exercise)
                    session.flush()
                prescription = ExercisePrescription(prescription_id=uid(), session_id=workout.session_id,
                    exercise_id=exercise.exercise_id, source_label=exercise_spec.name.strip(),
                    ordinal=exercise_ordinal, notes=exercise_spec.notes)
                session.add(prescription)
                session.flush()
                for set_index, set_spec in enumerate(exercise_spec.sets, 1):
                    session.add(PrescribedSet(prescribed_set_id=uid(), prescription_id=prescription.prescription_id,
                        set_index=set_spec.set_index or set_index, side=set_spec.side, set_type=set_spec.set_type,
                        target_reps=set_spec.target_reps, target_reps_min=set_spec.target_reps_min,
                        target_reps_max=set_spec.target_reps_max, target_load_kg=set_spec.target_load_kg,
                        target_rpe=set_spec.target_rpe, target_rpe_min=set_spec.target_rpe_min,
                        target_rpe_max=set_spec.target_rpe_max, target_rir=set_spec.target_rir,
                        target_rir_min=set_spec.target_rir_min, target_rir_max=set_spec.target_rir_max))
    return assignment


@app.post("/api/v1/versions/{version_id}/assign", status_code=201)
def assign(version_id: str, payload: AssignmentInput, actor: Account = Depends(coach), session: DBSession = Depends(db)):
    version = session.get(ProgramVersion, version_id)
    if not version:
        raise HTTPException(404, "Version not found")
    if len(set(payload.athlete_ids)) != len(payload.athlete_ids):
        raise HTTPException(422, "Duplicate client")
    for athlete_id in payload.athlete_ids:
        own_athlete(session, actor, athlete_id)
    made = []
    for athlete_id in payload.athlete_ids:
        for old in session.scalars(select(ProgramAssignment).where(ProgramAssignment.athlete_id == athlete_id,
                                                                   ProgramAssignment.active == 1)):
            old.active = 0
        assignment = materialize(session, version, athlete_id, payload.start_date)
        made.append(assignment.assignment_id)
        audit(session, actor, "program_assigned", assignment.assignment_id)
    session.commit()
    return {"assignment_ids": made}


def assigned_set(session: DBSession, athlete_id: str, set_id: str):
    return session.scalar(select(PrescribedSet).join(ExercisePrescription,
        PrescribedSet.prescription_id == ExercisePrescription.prescription_id).join(Session,
        ExercisePrescription.session_id == Session.session_id).join(TrainingWeek,
        Session.week_id == TrainingWeek.week_id).join(ProgramAssignment,
        TrainingWeek.block_id == ProgramAssignment.block_id).where(
        PrescribedSet.prescribed_set_id == set_id, ProgramAssignment.athlete_id == athlete_id))


def assigned_week(session: DBSession, athlete_id: str, week_id: str):
    return session.scalar(select(TrainingWeek).join(ProgramAssignment,
        TrainingWeek.block_id == ProgramAssignment.block_id).where(
        TrainingWeek.week_id == week_id, ProgramAssignment.athlete_id == athlete_id))


def program_view(session: DBSession, athlete_id: str):
    result = []
    assignments = session.scalars(select(ProgramAssignment).where(ProgramAssignment.athlete_id == athlete_id)
                                  .order_by(ProgramAssignment.created_at.desc())).all()
    for assignment in assignments:
        version = session.get(ProgramVersion, assignment.version_id)
        weeks = []
        for week in session.scalars(select(TrainingWeek).where(TrainingWeek.block_id == assignment.block_id)
                                    .order_by(TrainingWeek.week_index)):
            recovery = session.scalar(select(RecoveryCheckin).where(RecoveryCheckin.week_id == week.week_id))
            workouts = []
            for workout in session.scalars(select(Session).where(Session.week_id == week.week_id).order_by(Session.ordinal)):
                exercises = []
                for prescription in session.scalars(select(ExercisePrescription).where(
                    ExercisePrescription.session_id == workout.session_id).order_by(ExercisePrescription.ordinal)):
                    sets = []
                    for planned in session.scalars(select(PrescribedSet).where(
                        PrescribedSet.prescription_id == prescription.prescription_id).order_by(PrescribedSet.set_index)):
                        actual = session.scalar(select(ActualSet).where(ActualSet.prescribed_set_id == planned.prescribed_set_id))
                        sets.append({"id": planned.prescribed_set_id, "index": planned.set_index,
                                     "side": planned.side, "type": planned.set_type, "target_reps": planned.target_reps,
                                     "target_reps_min": planned.target_reps_min, "target_reps_max": planned.target_reps_max,
                                     "target_load_kg": planned.target_load_kg, "target_rpe": planned.target_rpe,
                                     "target_rpe_min": planned.target_rpe_min, "target_rpe_max": planned.target_rpe_max,
                                     "target_rir": planned.target_rir, "target_rir_min": planned.target_rir_min,
                                     "target_rir_max": planned.target_rir_max,
                                     "actual": ({"status": actual.status, "reps": actual.reps,
                                                 "load_kg": actual.load_kg, "actual_rpe": actual.actual_rpe,
                                                 "actual_rir": actual.actual_rir} if actual else None)})
                    exercises.append({"name": prescription.source_label, "notes": prescription.notes, "sets": sets})
                workouts.append({"id": workout.session_id, "label": workout.label,
                                 "date": workout.session_date, "exercises": exercises})
            weeks.append({"id": week.week_id, "index": week.week_index, "start_date": week.start_date,
                          "sessions": workouts,
                          "recovery_state": ("missing" if not recovery else "complete" if recovery.sleep_hours is not None and recovery.readiness is not None else "incomplete"),
                          "safety_review": bool(recovery and recovery.pain_notes),
                          "recovery": ({"sleep_hours": recovery.sleep_hours,
                          "readiness": recovery.readiness, "pain_notes": recovery.pain_notes} if recovery else None)})
        result.append({"id": assignment.assignment_id, "name": version.name, "version": version.version_no,
                       "start_date": assignment.start_date, "active": bool(assignment.active), "weeks": weeks})
    return {"assignments": result}


@app.get("/api/v1/me/program")
def my_program(actor: Account = Depends(client), session: DBSession = Depends(db)):
    return program_view(session, actor.athlete_id)


@app.get("/api/v1/athletes/{athlete_id}/program")
def coach_program(athlete_id: str, actor: Account = Depends(coach), session: DBSession = Depends(db)):
    own_athlete(session, actor, athlete_id)
    return program_view(session, athlete_id)


class ActualInput(BaseModel):
    status: str = Field(pattern="^(completed|failed|skipped|unreported)$")
    reps: float | None = Field(default=None, ge=0, le=1000)
    load_kg: float | None = Field(default=None, ge=0, le=2000)
    actual_rpe: float | None = Field(default=None, ge=0, le=10)
    actual_rir: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def consistent(self):
        values = (self.reps, self.load_kg, self.actual_rpe, self.actual_rir)
        if any(not math.isfinite(value) for value in values if value is not None):
            raise ValueError("Actual values must be finite")
        if self.status in {"skipped", "unreported"} and any(value is not None for value in values):
            raise ValueError("Skipped and unreported sets cannot have performance values")
        if self.status == "completed" and (self.reps is None or self.reps <= 0):
            raise ValueError("Completed sets require positive reps")
        if self.status == "failed" and self.reps != 0:
            raise ValueError("Failed sets require zero reps")
        return self


@app.put("/api/v1/me/sets/{set_id}")
def save_actual(set_id: str, payload: ActualInput, actor: Account = Depends(client), session: DBSession = Depends(db)):
    planned = assigned_set(session, actor.athlete_id, set_id)
    if not planned:
        raise HTTPException(404, "Set not found")
    actual = session.scalar(select(ActualSet).where(ActualSet.prescribed_set_id == set_id))
    prior = ({"status": actual.status, "reps": actual.reps, "load_kg": actual.load_kg,
              "actual_rpe": actual.actual_rpe, "actual_rir": actual.actual_rir} if actual else None)
    values = payload.model_dump()
    if prior == values:
        return {"changed": False}
    if not actual:
        actual = ActualSet(actual_set_id=uid(), prescription_id=planned.prescription_id,
                           prescribed_set_id=set_id, set_index=planned.set_index, side=planned.side,
                           is_extra=0, updated_at=stamp(), **values)
        session.add(actual)
    else:
        for field, value in values.items():
            setattr(actual, field, value)
        actual.updated_at = stamp()
    session.flush()
    session.add(ActualRevision(revision_id=uid(), actual_set_id=actual.actual_set_id,
                               actor_id=actor.account_id, prior_json=json.dumps(prior),
                               new_json=json.dumps(values), changed_at=stamp()))
    audit(session, actor, "actual_saved", set_id)
    session.commit()
    return {"changed": True}


class RecoveryInput(BaseModel):
    sleep_hours: float | None = Field(default=None, ge=0, le=24)
    readiness: int | None = Field(default=None, ge=1, le=10)
    pain_notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def finite(self):
        if self.sleep_hours is not None and not math.isfinite(self.sleep_hours):
            raise ValueError("Sleep hours must be finite")
        return self


@app.put("/api/v1/me/recovery/{week_id}")
def save_recovery(week_id: str, payload: RecoveryInput, actor: Account = Depends(client), session: DBSession = Depends(db)):
    if not assigned_week(session, actor.athlete_id, week_id):
        raise HTTPException(404, "Week not found")
    checkin = session.scalar(select(RecoveryCheckin).where(RecoveryCheckin.week_id == week_id))
    prior = ({"sleep_hours": checkin.sleep_hours, "readiness": checkin.readiness,
              "pain_notes": checkin.pain_notes} if checkin else None)
    values = payload.model_dump()
    if prior == values:
        return {"changed": False}
    if not checkin:
        checkin = RecoveryCheckin(checkin_id=uid(), athlete_id=actor.athlete_id,
                                   week_id=week_id, updated_at=stamp(), **values)
        session.add(checkin)
    else:
        for field, value in values.items():
            setattr(checkin, field, value)
        checkin.updated_at = stamp()
    session.flush()
    session.add(RecoveryRevision(revision_id=uid(), checkin_id=checkin.checkin_id,
                                 actor_id=actor.account_id, prior_json=json.dumps(prior),
                                 new_json=json.dumps(values), changed_at=stamp()))
    audit(session, actor, "recovery_saved", week_id)
    session.commit()
    return {"changed": True, "state": "complete" if values["sleep_hours"] is not None and values["readiness"] is not None else "incomplete",
            "review_required": bool(values["pain_notes"])}


@app.get("/api/v1/athletes/{athlete_id}/analytics")
def athlete_analytics(athlete_id: str, actor: Account = Depends(coach), session: DBSession = Depends(db)):
    own_athlete(session, actor, athlete_id)
    rows = []
    query = select(PrescribedSet, ActualSet, ExercisePrescription.exercise_id).join(
        ExercisePrescription, PrescribedSet.prescription_id == ExercisePrescription.prescription_id).join(
        Session, ExercisePrescription.session_id == Session.session_id).join(
        TrainingWeek, Session.week_id == TrainingWeek.week_id).join(
        TrainingBlock, TrainingWeek.block_id == TrainingBlock.block_id).outerjoin(
        ActualSet, ActualSet.prescribed_set_id == PrescribedSet.prescribed_set_id).where(
        TrainingBlock.athlete_id == athlete_id)
    for planned, actual, exercise_id in session.execute(query):
        rows.append({"id": planned.prescribed_set_id, "exercise_id": exercise_id, "set_type": planned.set_type,
                     "side": planned.side, "target_reps": planned.target_reps,
                     "target_reps_min": planned.target_reps_min, "target_reps_max": planned.target_reps_max,
                     "target_rpe": planned.target_rpe, "target_rpe_min": planned.target_rpe_min,
                     "target_rpe_max": planned.target_rpe_max, "target_rir": planned.target_rir,
                     "status": actual.status if actual else None, "reps": actual.reps if actual else None,
                     "load_kg": actual.load_kg if actual else None,
                     "actual_rpe": actual.actual_rpe if actual else None, "source": None})
    return {"athlete_id": athlete_id, "metrics": compute(rows), "sets": rows}


@app.get("/api/v1/athletes/{athlete_id}/history")
def athlete_history(athlete_id: str, actor: Account = Depends(coach), session: DBSession = Depends(db)):
    own_athlete(session, actor, athlete_id)
    actuals = session.execute(select(ActualRevision).join(ActualSet,
        ActualRevision.actual_set_id == ActualSet.actual_set_id).join(ExercisePrescription,
        ActualSet.prescription_id == ExercisePrescription.prescription_id).join(Session,
        ExercisePrescription.session_id == Session.session_id).join(TrainingWeek,
        Session.week_id == TrainingWeek.week_id).join(TrainingBlock,
        TrainingWeek.block_id == TrainingBlock.block_id).where(TrainingBlock.athlete_id == athlete_id)
        .order_by(ActualRevision.changed_at.desc()).limit(100)).scalars().all()
    recovery = session.scalars(select(RecoveryRevision).join(RecoveryCheckin,
        RecoveryRevision.checkin_id == RecoveryCheckin.checkin_id).where(
        RecoveryCheckin.athlete_id == athlete_id).order_by(RecoveryRevision.changed_at.desc()).limit(100)).all()
    return {"actuals": [{"target_id": item.actual_set_id, "prior": json.loads(item.prior_json),
                         "new": json.loads(item.new_json), "at": item.changed_at} for item in actuals],
            "recovery": [{"target_id": item.checkin_id, "prior": json.loads(item.prior_json),
                          "new": json.loads(item.new_json), "at": item.changed_at} for item in recovery]}


@app.get("/api/v1/audit")
def audit_log(actor: Account = Depends(coach), session: DBSession = Depends(db)):
    return {"items": [{"action": item.action, "target_id": item.target_id, "at": item.occurred_at}
                      for item in session.scalars(select(AuditEvent).order_by(AuditEvent.occurred_at.desc()).limit(100))]}


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(min_length=12, max_length=1024)
    mfa_code: str = ""


@app.post("/api/v1/auth/password")
def change_password(payload: PasswordChange, request: Request, actor: Account = Depends(current),
                    session: DBSession = Depends(db)):
    try:
        hasher.verify(actor.password_hash, payload.current_password)
    except Exception:
        raise HTTPException(401, "Invalid credentials") from None
    if actor.role == "coach" and not verify_mfa(actor, payload.mfa_code):
        raise HTTPException(401, "Invalid credentials")
    actor.password_hash = hasher.hash(payload.new_password)
    for auth in session.scalars(select(AuthSession).where(AuthSession.account_id == actor.account_id,
                                                         AuthSession.revoked_at.is_(None))):
        if auth.token_hash != digest(request.cookies[SESSION_COOKIE]):
            auth.revoked_at = stamp()
    audit(session, actor, "password_changed")
    session.commit()
    return {"ok": True}


def init_coach():
    with SessionLocal() as session:
        if session.scalar(select(Account).where(Account.role == "coach")):
            raise SystemExit("Coach already exists")
        address = email_key(input("Coach email: "))
        password = getpass("New password (12+ characters): ")
        if len(password) < 12 or password != getpass("Confirm password: "):
            raise SystemExit("Passwords must match and contain at least 12 characters")
        secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
        print("Add this TOTP secret to your authenticator app:", secret)
        if not secrets.compare_digest(totp(secret), input("Current six-digit code: ").strip()):
            raise SystemExit("Authenticator code did not match. No account was created.")
        codes = [secrets.token_hex(8).upper() for _ in range(8)]
        account = Account(account_id=uid(), role="coach", athlete_id=None, email=address,
                          password_hash=hasher.hash(password), mfa_secret=secret,
                          recovery_hashes_json=json.dumps([digest(code) for code in codes]), created_at=stamp())
        session.add(account)
        session.commit()
        print("Save these one-time recovery codes outside the server:")
        for code in codes:
            print(code)


dist = Path(__file__).resolve().parents[1] / "dist"
if dist.exists():
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def frontend(path: str):
        if path not in {"", "portal", "invite"}:
            raise HTTPException(404, "Page not found")
        if not path:
            return RedirectResponse("/portal")
        return FileResponse(dist / "index.html")


if __name__ == "__main__":
    init_coach()
