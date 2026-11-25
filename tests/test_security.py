import hashlib
import io
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from openpyxl import Workbook
import sqlcipher3

from strengthos import main, storage
from strengthos.db import make_engine
from sqlalchemy.orm import sessionmaker


class SecurityTests(unittest.TestCase):
    def test_migrate_and_restore_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            legacy, private = base / "legacy", base / "private"
            (legacy / "uploads").mkdir(parents=True)
            ident, content = str(uuid4()), b"synthetic workbook"
            with closing(sqlite3.connect(legacy / "strengthos.db")) as db:
                db.execute("CREATE TABLE import_jobs(import_id TEXT PRIMARY KEY,source_snapshot_hash TEXT,snapshot_path TEXT)")
                db.execute("INSERT INTO import_jobs VALUES (?,?,?)", (ident, hashlib.sha256(content).hexdigest(), "legacy"))
                db.commit()
            with self.assertRaises(FileNotFoundError):
                storage.migrate(legacy, private)
            self.assertFalse(private.exists())
            (legacy / "uploads" / (ident + ".xlsx")).write_bytes(content)
            storage.migrate(legacy, private)
            phrase, saved = "synthetic recovery phrase", base / "copy.strengthbackup"
            with patch.dict(os.environ, STRENGTHOS_DATA_DIR=str(private)):
                storage.backup(saved, phrase)
            self.assertNotIn(content, saved.read_bytes())
            self.assertFalse((private / "strengthos.db").read_bytes().startswith(b"SQLite format"))
            restored = base / "clean"
            with self.assertRaises(sqlcipher3.DatabaseError):
                storage.restore(saved, "wrong", restored)
            self.assertFalse(restored.exists())
            storage.restore(saved, phrase, restored)
            with closing(storage.connect(restored / "strengthos.db", storage.device_key(restored))) as db:
                self.assertEqual(db.execute("SELECT content FROM workbook_snapshots").fetchone(), (content,))

    def test_http_contract(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, STRENGTHOS_DATA_DIR=tmp):
            root = Path(tmp)
            engine = make_engine()
            try:
                with patch("strengthos.db.engine", engine):
                    command.upgrade(Config("alembic.ini"), "head")
                with patch.object(main, "data_dir", root), patch.object(main, "SessionLocal", sessionmaker(engine)), patch.object(main, "sessions", {}):
                    main.attempts.clear()
                    client = TestClient(main.app, base_url="http://localhost")
                    self.assertEqual(client.get("/api/v1/auth/setup-status", headers={"Host": "127.0.0.1:8000"}).status_code, 200)
                    auth = {"email": "synthetic@example.com", "password": "synthetic-password"}
                    self.assertEqual(client.get("/sign-in", headers={"Host": "external.invalid"}).status_code, 400)
                    self.assertEqual(client.post("/api/v1/auth/signup", json=auth, headers={"Origin": "https://external.invalid"}).status_code, 403)
                    client.headers.update({"Origin": "http://localhost"})
                    self.assertEqual(client.post("/api/v1/auth/signup", json=auth).status_code, 201)
                    csrf = client.post("/api/v1/auth/login", json=auth).json()["csrf_token"]
                    self.assertEqual(client.post("/api/v1/athletes", json={"display_name":"A"}).status_code, 403)
                    client.headers.update({"X-CSRF-Token": csrf})
                    athletes = [client.post("/api/v1/athletes", json={"display_name": name}).json()["athlete_id"] for name in ("A", "B")]
                    book = Workbook()
                    book.active.append(["exercise", "reps"])
                    buf = io.BytesIO()
                    book.save(buf)
                    files = {"file": ("synthetic.xlsx", buf.getvalue())}
                    uploaded = client.post("/api/v1/imports/excel", data={"athlete_id": athletes[0]}, files=files)
                    self.assertEqual(uploaded.status_code, 200)
                    source = uploaded.json()["source_id"]
                    self.assertEqual(client.post("/api/v1/imports/excel", data={"athlete_id": athletes[1], "source_id": source}, files=files).status_code, 404)
                    self.assertEqual(client.post("/api/v1/imports/excel", data={"athlete_id": athletes[0]}, files={"file": ("bad.xlsx", b"invalid")}).status_code, 422)
                    book.active.cell(1, 201, "synthetic")
                    buf = io.BytesIO()
                    book.save(buf)
                    limited = client.post("/api/v1/imports/excel", data={"athlete_id": athletes[0]}, files={"file": ("wide.xlsx", buf.getvalue())})
                    self.assertEqual(limited.status_code, 422)
                    self.assertIn("200 columns", limited.json()["detail"])
                    self.assertEqual(client.get("/.git/config").status_code, 404)
                    response = client.post("/api/v1/backups", json={"passphrase": "synthetic backup passphrase"})
                    self.assertEqual(response.status_code, 200)
                    self.assertNotIn(b"synthetic@example.com", response.content)
                    token = client.cookies["strengthos_session"]
                    main.sessions[token] = (csrf, 0)
                    self.assertEqual(client.get("/api/v1/athletes").status_code, 401)
                    for _ in range(5):
                        client.post("/api/v1/auth/login", json={**auth, "password": "wrong"})
                    self.assertEqual(client.post("/api/v1/auth/login", json=auth).status_code, 429)
                    main.attempts.clear()
            finally:
                engine.dispose()
