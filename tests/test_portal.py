import os
import tempfile
import unittest
import io
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy import inspect
from sqlalchemy.orm import sessionmaker

from strengthos.db import Account, ActualRevision, ActualSet, ClientInvite, ProgramVersion, RecoveryRevision, make_engine
from strengthos import transfer

ORIGIN = "http://127.0.0.1:8001"
with patch.dict(os.environ, STRENGTHOS_DATABASE_URL="sqlite://", STRENGTHOS_PUBLIC_ORIGIN=ORIGIN):
    from strengthos import hosted


class PortalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.engine = make_engine("sqlite:///" + str(Path(self.temp.name) / "portal.db"))
        with patch("strengthos.db.engine", self.engine):
            command.upgrade(Config("alembic.ini"), "head")
        self.sessions = sessionmaker(self.engine)
        self.binding = patch.object(hosted, "SessionLocal", self.sessions)
        self.binding.start()
        hosted.login_attempts.clear()
        secret = "JBSWY3DPEHPK3PXP"
        with self.sessions() as db:
            db.add(Account(account_id=hosted.uid(), role="coach", email="coach@example.com", athlete_id=None,
                           password_hash=hosted.hasher.hash("coach-password-123"), mfa_secret=secret,
                           recovery_hashes_json="[]", created_at=hosted.stamp()))
            db.commit()
        self.coach = TestClient(hosted.app, base_url=ORIGIN, headers={"Origin": ORIGIN})
        self.assertEqual(self.coach.post("/api/v1/auth/login", json={"email": "coach@example.com",
            "password": "coach-password-123", "mfa_code": hosted.totp(secret)}).status_code, 200)
        self.coach.headers["X-CSRF-Token"] = self.coach.post("/api/v1/auth/login", json={"email": "coach@example.com",
            "password": "coach-password-123", "mfa_code": hosted.totp(secret)}).json()["csrf_token"]

    def tearDown(self):
        self.binding.stop()
        self.engine.dispose()
        self.temp.cleanup()

    def invite(self, athlete_id, email):
        result = self.coach.post(f"/api/v1/athletes/{athlete_id}/invites", json={"email": email})
        self.assertEqual(result.status_code, 201, result.text)
        token = result.json()["url"].split("token=")[1]
        user = TestClient(hosted.app, base_url=ORIGIN, headers={"Origin": ORIGIN})
        self.assertEqual(user.post("/api/v1/auth/invites/accept", json={"token": token,
            "password": "client-password-123"}).status_code, 201)
        self.assertEqual(user.post("/api/v1/auth/invites/accept", json={"token": token,
            "password": "client-password-123"}).status_code, 404)
        login = user.post("/api/v1/auth/login", json={"email": email, "password": "client-password-123"})
        self.assertEqual(login.status_code, 200, login.text)
        user.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        return user

    def test_publish_assign_scope_and_revisions(self):
        self.assertEqual(self.coach.post("/api/v1/athletes", json={"display_name": "No CSRF"},
                                        headers={"X-CSRF-Token": "wrong"}).status_code, 403)
        athletes = [self.coach.post("/api/v1/athletes", json={"display_name": name}).json()["athlete_id"]
                    for name in ("Client A", "Client B")]
        draft = {"weeks": [{"sessions": [{"label": "Day 1", "day_offset": 0,
            "exercises": [{"name": "Squat", "sets": [{"set_type": "working", "target_reps": 5,
            "target_load_kg": 80, "target_rpe": 8}, {"set_type": "working", "target_reps_min": 6,
            "target_reps_max": 8}]}]}]}]}
        template = self.coach.post("/api/v1/templates", json={"name": "Base program", "program": draft})
        self.assertEqual(template.status_code, 201, template.text)
        template_id = template.json()["template_id"]
        version = self.coach.post(f"/api/v1/templates/{template_id}/publish")
        self.assertEqual(version.status_code, 201, version.text)
        version_id = version.json()["version_id"]
        draft["weeks"][0]["sessions"][0]["exercises"][0]["sets"][0]["target_reps"] = 10
        self.assertEqual(self.coach.put(f"/api/v1/templates/{template_id}",
            json={"name": "Base program", "program": draft}).status_code, 200)
        with self.sessions() as db:
            self.assertEqual(db.get(ProgramVersion, version_id).snapshot_json.count('"target_reps":5'), 1)
        assigned = self.coach.post(f"/api/v1/versions/{version_id}/assign", json={
            "athlete_ids": athletes, "start_date": "2026-12-01"})
        self.assertEqual(assigned.status_code, 201, assigned.text)
        a = self.invite(athletes[0], "a@example.com")
        b = self.invite(athletes[1], "b@example.com")
        program_a = a.get("/api/v1/me/program").json()["assignments"][0]
        set_a = program_a["weeks"][0]["sessions"][0]["exercises"][0]["sets"][0]
        self.assertEqual(set_a["target_reps"], 5)
        self.assertEqual(program_a["weeks"][0]["sessions"][0]["exercises"][0]["sets"][1]["target_reps_min"], 6)
        self.assertEqual(program_a["weeks"][0]["sessions"][0]["date"], "2026-12-01")
        self.assertEqual(b.put(f"/api/v1/me/sets/{set_a['id']}", json={"status": "completed", "reps": 5}).status_code, 404)
        self.assertEqual(a.get(f"/api/v1/athletes/{athletes[1]}/program").status_code, 403)
        self.assertEqual(a.get(f"/api/v1/athletes/{athletes[1]}/history").status_code, 403)
        self.assertEqual(a.get("/api/v1/audit").status_code, 403)
        self.assertEqual(a.post(f"/api/v1/templates/{template_id}/publish").status_code, 403)
        self.assertEqual(a.put(f"/api/v1/me/sets/{set_a['id']}", json={"status": "failed", "reps": 1}).status_code, 422)
        self.assertEqual(a.put(f"/api/v1/me/sets/{set_a['id']}", json={"status": "failed", "reps": 0}).status_code, 200)
        self.assertEqual(a.put(f"/api/v1/me/sets/{set_a['id']}", json={"status": "skipped"}).status_code, 200)
        self.assertEqual(a.put(f"/api/v1/me/sets/{set_a['id']}", json={"status": "skipped"}).json()["changed"], False)
        week_id = program_a["weeks"][0]["id"]
        self.assertEqual(b.put(f"/api/v1/me/recovery/{week_id}", json={"readiness": 8}).status_code, 404)
        self.assertEqual(a.put(f"/api/v1/me/recovery/{week_id}", json={"readiness": 8}).json()["state"], "incomplete")
        self.assertEqual(a.put(f"/api/v1/me/recovery/{week_id}", json={
            "readiness": 8, "sleep_hours": 7, "pain_notes": "Knee concern"}).json()["review_required"], True)
        with self.sessions() as db:
            self.assertEqual(db.scalar(select(ActualSet).where(ActualSet.prescribed_set_id == set_a["id"])).status, "skipped")
            self.assertEqual(len(db.scalars(select(ActualRevision)).all()), 2)
            self.assertEqual(len(db.scalars(select(RecoveryRevision)).all()), 2)
        self.assertEqual(len(self.coach.get(f"/api/v1/athletes/{athletes[0]}/history").json()["actuals"]), 2)
        next_version = self.coach.post(f"/api/v1/templates/{template_id}/publish").json()["version_id"]
        self.assertEqual(self.coach.post(f"/api/v1/versions/{next_version}/assign", json={
            "athlete_ids": [athletes[0]], "start_date": "2026-12-08"}).status_code, 201)
        weeks = a.get("/api/v1/me/program").json()["assignments"]
        self.assertEqual(len(weeks), 2)
        self.assertEqual(weeks[0]["weeks"][0]["sessions"][0]["exercises"][0]["sets"][0]["target_reps"], 10)
        self.assertIsNone(weeks[0]["weeks"][0]["sessions"][0]["exercises"][0]["sets"][0]["actual"])
        self.assertEqual(weeks[1]["weeks"][0]["sessions"][0]["exercises"][0]["sets"][0]["actual"]["status"], "skipped")

    def test_mfa_and_invite_scope(self):
        bad = TestClient(hosted.app, base_url=ORIGIN, headers={"Origin": ORIGIN})
        self.assertEqual(bad.post("/api/v1/auth/login", json={"email": "coach@example.com", "password": "x"},
                                  headers={"Origin": "https://other.example"}).status_code, 403)
        self.assertEqual(bad.get("/api/v1/health", headers={"Host": "other.example"}).status_code, 400)
        self.assertEqual(bad.post("/api/v1/auth/login", json={"email": "coach@example.com",
            "password": "coach-password-123", "mfa_code": "000000"}).status_code, 401)
        athlete = self.coach.post("/api/v1/athletes", json={"display_name": "Client"}).json()["athlete_id"]
        user = self.invite(athlete, "client@example.com")
        pending = self.coach.post(f"/api/v1/athletes/{athlete}/invites", json={"email": "client@example.com"}).json()
        self.assertEqual(self.coach.post(f"/api/v1/athletes/{athlete}/deactivate").status_code, 200)
        self.assertEqual(user.get("/api/v1/me/program").status_code, 401)
        self.assertEqual(bad.post("/api/v1/auth/invites/accept", json={
            "token": pending["url"].split("token=")[1], "password": "new-password-123"}).status_code, 404)

    def test_loopback_coach_enrollment_closes_after_first_account(self):
        fresh = make_engine("sqlite:///" + str(Path(self.temp.name) / "setup.db"))
        try:
            with patch("strengthos.db.engine", fresh):
                command.upgrade(Config("alembic.ini"), "head")
            with patch.object(hosted, "SessionLocal", sessionmaker(fresh)):
                browser = TestClient(hosted.app, base_url=ORIGIN, headers={"Origin": ORIGIN})
                self.assertTrue(browser.get("/api/v1/auth/setup-status").json()["signup_available"])
                started = browser.post("/api/v1/auth/setup/start", json={
                    "email": "newcoach@example.com", "password": "new-coach-password-123"})
                self.assertEqual(started.status_code, 200, started.text)
                enrollment = started.json()
                self.assertEqual(browser.post("/api/v1/auth/setup/finish", json={
                    "enrollment_id": enrollment["enrollment_id"], "mfa_code": "000000"}).status_code, 422)
                finished = browser.post("/api/v1/auth/setup/finish", json={
                    "enrollment_id": enrollment["enrollment_id"],
                    "mfa_code": hosted.totp(enrollment["totp_secret"])})
                self.assertEqual(finished.status_code, 201, finished.text)
                self.assertEqual(len(finished.json()["recovery_codes"]), 8)
                self.assertFalse(browser.get("/api/v1/auth/setup-status").json()["signup_available"])
                self.assertEqual(browser.post("/api/v1/auth/setup/start", json={
                    "email": "second@example.com", "password": "new-coach-password-123"}).status_code, 409)
                self.assertEqual(browser.post("/api/v1/auth/login", json={
                    "email": "newcoach@example.com", "password": "new-coach-password-123",
                    "mfa_code": hosted.totp(enrollment["totp_secret"])}).status_code, 200)
                with patch.object(hosted, "DEV", False):
                    self.assertEqual(browser.get("/api/v1/auth/setup-status").json()["signup_available"], False)
                    self.assertEqual(browser.post("/api/v1/auth/setup/start", json={
                        "email": "public@example.com", "password": "new-coach-password-123"}).status_code, 404)
        finally:
            hosted.setup_pending.clear()
            fresh.dispose()

    def test_local_access_requires_loopback_and_keeps_csrf(self):
        with patch.object(hosted, "LOCAL_BYPASS", True):
            browser = TestClient(hosted.app, base_url=ORIGIN, headers={"Origin": ORIGIN},
                                 client=("127.0.0.1", 45000))
            self.assertEqual(browser.get("/api/v1/auth/me").status_code, 401)
            entered = browser.post("/api/v1/auth/local-access", json={})
            self.assertEqual(entered.status_code, 200, entered.text)
            self.assertEqual(entered.json()["role"], "coach")
            self.assertEqual(browser.get("/api/v1/auth/me").status_code, 200)
            draft = {"name": "Week", "program": {"weeks": []}}
            self.assertEqual(browser.post("/api/v1/templates", json=draft).status_code, 403)
            browser.headers["X-CSRF-Token"] = entered.json()["csrf_token"]
            self.assertEqual(browser.post("/api/v1/templates", json=draft).status_code, 201)
            remote = TestClient(hosted.app, base_url=ORIGIN, headers={"Origin": ORIGIN},
                                client=("198.51.100.5", 45000))
            self.assertEqual(remote.post("/api/v1/auth/local-access", json={}).status_code, 403)
        self.assertEqual(browser.post("/api/v1/auth/local-access", json={}).status_code, 404)

    def test_local_access_creates_only_one_preview_coach(self):
        fresh = make_engine("sqlite:///" + str(Path(self.temp.name) / "local-access.db"))
        try:
            with patch("strengthos.db.engine", fresh):
                command.upgrade(Config("alembic.ini"), "head")
            with patch.object(hosted, "SessionLocal", sessionmaker(fresh)), patch.object(hosted, "LOCAL_BYPASS", True):
                browser = TestClient(hosted.app, base_url=ORIGIN, headers={"Origin": ORIGIN},
                                     client=("127.0.0.1", 45000))
                self.assertEqual(browser.post("/api/v1/auth/local-access", json={}).status_code, 200)
                self.assertEqual(browser.post("/api/v1/auth/local-access", json={}).status_code, 200)
                with sessionmaker(fresh)() as db:
                    self.assertEqual(len(db.scalars(select(Account)).all()), 1)
                self.assertFalse(browser.get("/api/v1/auth/setup-status").json()["signup_available"])
        finally:
            fresh.dispose()

    def test_session_revocation_and_invite_expiry(self):
        athlete = self.coach.post("/api/v1/athletes", json={"display_name": "Client"}).json()["athlete_id"]
        user = self.invite(athlete, "client@example.com")
        other = TestClient(hosted.app, base_url=ORIGIN, headers={"Origin": ORIGIN})
        other_login = other.post("/api/v1/auth/login", json={"email": "client@example.com",
            "password": "client-password-123"})
        self.assertEqual(other_login.status_code, 200)
        self.assertEqual(len(user.get("/api/v1/auth/sessions").json()["items"]), 2)
        self.assertEqual(user.post("/api/v1/auth/sessions/revoke-others").status_code, 200)
        self.assertEqual(other.get("/api/v1/auth/me").status_code, 401)
        new_invite = self.coach.post(f"/api/v1/athletes/{athlete}/invites", json={
            "email": "client@example.com"}).json()
        with self.sessions() as db:
            invite = db.get(ClientInvite, new_invite["invite_id"])
            invite.expires_at = "2000-01-01T00:00:00+00:00"
            db.commit()
        token = new_invite["url"].split("token=")[1]
        self.assertEqual(other.post("/api/v1/auth/invites/accept", json={"token": token,
            "password": "another-password-123"}).status_code, 404)

    def test_portal_migration_downgrade_and_upgrade(self):
        with patch("strengthos.db.engine", self.engine):
            command.downgrade(Config("alembic.ini"), "0002")
            self.assertNotIn("accounts", inspect(self.engine).get_table_names())
            command.upgrade(Config("alembic.ini"), "head")
            self.assertIn("accounts", inspect(self.engine).get_table_names())

    def test_workbook_requires_preview_and_coach_approval(self):
        book = Workbook()
        sheet = book.active
        sheet.title = "Training"
        sheet.append(["Block", "Week", "Session", "Exercise", "Set", "Reps"])
        sheet.append(["Base", "Week 1", "Day 1", "Squat", 1, 5])
        output = io.BytesIO()
        book.save(output)
        uploaded = self.coach.post("/api/v1/template-imports", files={"file": ("synthetic.xlsx", output.getvalue())})
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        ident, content_hash = uploaded.json()["import_id"], uploaded.json()["content_hash"]
        mapping = {"layout": "row_per_set", "schema_version": 2, "sheet": "Training", "header_row": 1,
                   "columns": {"block": "A", "week": "B", "session": "C", "exercise_label": "D",
                               "set_index": "E", "target_reps": "F"}, "exercise_aliases": {"Squat": "Squat"}}
        self.assertEqual(self.coach.post(f"/api/v1/template-imports/{ident}/approve", json={
            "mapping": mapping, "acknowledged_hash": content_hash, "mapping_hash": hosted.mapping_digest(mapping),
            "approve": True}).status_code, 422)
        preview = self.coach.post(f"/api/v1/template-imports/{ident}/preview", json={"mapping": mapping})
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.json()["row_count"], 1)
        approved = self.coach.post(f"/api/v1/template-imports/{ident}/approve", json={
            "mapping": mapping, "acknowledged_hash": content_hash,
            "mapping_hash": preview.json()["mapping_hash"], "approve": True})
        self.assertEqual(approved.status_code, 201, approved.text)
        self.assertEqual(self.coach.post(f"/api/v1/template-imports/{ident}/preview", json={"mapping": mapping}).status_code, 404)
        self.assertEqual(self.coach.get("/api/v1/templates").json()["items"][0]["name"], "Base")

    def test_encrypted_transfer_requires_review_and_fresh_database(self):
        self.coach.post("/api/v1/athletes", json={"display_name": "Synthetic client"})
        destination = Path(self.temp.name) / "approved.strengthtransfer"
        phrase = "synthetic transfer phrase"
        with patch.object(transfer, "SessionLocal", self.sessions):
            counts = transfer.export_file(destination, phrase)
        self.assertEqual(counts["athletes"], 1)
        self.assertNotIn(b"Synthetic client", destination.read_bytes())
        with self.assertRaises(ValueError):
            transfer.unseal(destination.read_bytes(), "incorrect passphrase")
        second_engine = make_engine("sqlite:///" + str(Path(self.temp.name) / "fresh.db"))
        try:
            with patch("strengthos.db.engine", second_engine):
                command.upgrade(Config("alembic.ini"), "head")
            with patch.object(transfer, "SessionLocal", sessionmaker(second_engine)):
                self.assertEqual(transfer.import_file(destination, phrase)["athletes"], 1)
                self.assertEqual(transfer.import_file(destination, phrase, confirmed=True)["athletes"], 1)
                with self.assertRaises(ValueError):
                    transfer.import_file(destination, phrase, confirmed=True)
        finally:
            second_engine.dispose()


if __name__ == "__main__":
    unittest.main()
