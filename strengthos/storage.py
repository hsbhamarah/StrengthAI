"""Local encrypted storage. Portable backups use SQLCipher's passphrase format."""
import hashlib
import os
import secrets
import tempfile
from contextlib import closing
from getpass import getpass
from pathlib import Path
from uuid import UUID

import sqlcipher3
import win32crypt


def private_dir():
    override = os.environ.get("STRENGTHOS_DATA_DIR")
    return Path(override) if override else Path(os.environ["LOCALAPPDATA"]) / "StrengthOS"


def device_key(root):
    root.mkdir(parents=True, exist_ok=True)
    keyfile = root / "workspace.dpapi"
    if not keyfile.exists():
        if (root / "strengthos.db").exists():
            raise RuntimeError("Workspace key missing. Restore an encrypted backup.")
        sealed = win32crypt.CryptProtectData(secrets.token_bytes(32), "StrengthOS", None, None, None, 1)
        with tempfile.NamedTemporaryFile(dir=root, delete=False) as temp:
            temp.write(sealed)
        try:
            Path(temp.name).rename(keyfile)  # Windows refuses to replace an existing key.
        except FileExistsError:
            Path(temp.name).unlink()
    return win32crypt.CryptUnprotectData(keyfile.read_bytes(), None, None, None, 1)[1].hex()


def connect(path, password):
    db = sqlcipher3.connect(str(path), check_same_thread=False)
    try:
        db.set_key(password.encode("utf-8"))
        db.execute("PRAGMA temp_store=MEMORY")
        db.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return db
    except Exception:
        db.close()
        raise


def export(db, destination, password):
    """Export one consistent transaction and check all copied tables."""
    db.execute("ATTACH DATABASE ? AS saved KEY ?", (str(destination), password))
    try:
        db.execute("BEGIN")
        db.execute("SELECT sqlcipher_export('saved')").fetchone()
        for name, in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            table = '"' + name.replace('"', '""') + '"'
            primary = sorted((col[5], col[1]) for col in db.execute(f"PRAGMA main.table_info({table})") if col[5])
            order = ", ".join('"' + col.replace('"', '""') + '"' for _, col in primary) or "rowid"
            original = db.execute(f"SELECT * FROM main.{table} ORDER BY {order}")
            copied = db.execute(f"SELECT * FROM saved.{table} ORDER BY {order}")
            for before, after in zip(original, copied, strict=True):
                if before != after:
                    raise ValueError("Export verification failed")
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute("DETACH DATABASE saved")
    with closing(connect(destination, password)) as copy:
        if copy.execute("PRAGMA integrity_check").fetchone() != ("ok",) or copy.execute("PRAGMA cipher_integrity_check").fetchall():
            raise ValueError("Export integrity check failed")


def migrate(legacy, root):
    """Publish a verified sibling directory. Leave the original available for rollback."""
    if root.exists():
        if not (root / "workspace.dpapi").is_file():
            raise ValueError("Destination exists without a workspace key. Choose an unused folder.")
        return
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root.parent) as temp:
        stage = Path(temp) / "workspace"
        key = device_key(stage)
        if (legacy / "strengthos.db").exists():
            with closing(sqlcipher3.connect(str(legacy / "strengthos.db"))) as old:
                export(old, stage / "strengthos.db", key)
            with closing(connect(stage / "strengthos.db", key)) as db:
                db.execute("CREATE TABLE IF NOT EXISTS workbook_snapshots (import_id TEXT PRIMARY KEY REFERENCES import_jobs(import_id), content BLOB NOT NULL)")
                for ident, digest in db.execute("SELECT import_id,source_snapshot_hash FROM import_jobs"):
                    content = (legacy / "uploads" / (str(UUID(ident)) + ".xlsx")).read_bytes()
                    if hashlib.sha256(content).hexdigest() != digest:
                        raise ValueError("A retained workbook failed verification")
                    db.execute("INSERT INTO workbook_snapshots VALUES (?,?)", (ident, content))
                    db.execute("UPDATE import_jobs SET snapshot_path=? WHERE import_id=?", ("database", ident))
                db.commit()
        from strengthos.setup import credentials, save_credentials
        email, password_hash = credentials(legacy)
        if email or password_hash:
            save_credentials(stage, email, password_hash)
        stage.rename(root)


def backup(destination, phrase):
    if len(phrase) < 16 or "\x00" in phrase:
        raise ValueError("Use a recovery passphrase of at least 16 characters")
    root = private_dir()
    if not (root / "strengthos.db").is_file():
        raise ValueError("No workspace to back up")
    with tempfile.TemporaryDirectory(dir=destination.parent) as temp:
        saved = Path(temp) / "backup"
        with closing(connect(root / "strengthos.db", device_key(root))) as db:
            export(db, saved, phrase)
        saved.rename(destination)


def restore(source, phrase, root):
    if root.exists() or not source.is_file() or not phrase or "\x00" in phrase:
        raise ValueError("Restore requires an existing backup and an unused destination")
    root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root.parent) as temp:
        stage = Path(temp) / "workspace"
        with closing(connect(source, phrase)) as db:
            db.execute("SELECT content FROM workbook_snapshots LIMIT 0")
            export(db, stage / "strengthos.db", device_key(stage))
        stage.rename(root)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["migrate", "backup", "restore"])
    parser.add_argument("file", nargs="?", type=Path)
    args = parser.parse_args()
    if args.action == "migrate":
        migrate(Path(__file__).resolve().parents[1] / "data", private_dir())
    elif args.file is None:
        parser.error("Choose a backup file")
    elif args.action == "backup":
        phrase = getpass("Backup recovery passphrase: ")
        if phrase != getpass("Confirm recovery passphrase: "):
            parser.error("Passphrases differ")
        backup(args.file, phrase)
    else:
        restore(args.file, getpass("Backup recovery passphrase: "), private_dir())
