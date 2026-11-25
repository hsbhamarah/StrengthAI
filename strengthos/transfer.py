"""Encrypted, reviewed transfer of approved local records to a fresh hosted database."""
from __future__ import annotations

import json
import os
import secrets
import sys
import zlib
from getpass import getpass
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from sqlalchemy import select

from strengthos.db import Base, SessionLocal

MAGIC = b"STRENGTHOS-TRANSFER-1\n"
ORDER = ["athletes", "training_blocks", "training_weeks", "sessions", "exercises",
         "exercise_prescriptions", "prescribed_sets", "actual_sets", "data_sources",
         "mapping_profiles", "import_jobs", "source_records", "record_revisions"]


def key_from(passphrase: str, salt: bytes) -> bytes:
    if len(passphrase) < 16:
        raise ValueError("Transfer passphrase must contain at least 16 characters")
    return Scrypt(salt=salt, length=32, n=2 ** 17, r=8, p=1).derive(passphrase.encode())


def seal(payload: dict, passphrase: str) -> bytes:
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    clear = zlib.compress(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(), 9)
    return MAGIC + salt + nonce + AESGCM(key_from(passphrase, salt)).encrypt(nonce, clear, MAGIC)


def unseal(content: bytes, passphrase: str) -> dict:
    if not content.startswith(MAGIC) or len(content) < len(MAGIC) + 28:
        raise ValueError("Invalid transfer file")
    offset = len(MAGIC)
    salt, nonce, ciphertext = content[offset:offset + 16], content[offset + 16:offset + 28], content[offset + 28:]
    try:
        return json.loads(zlib.decompress(AESGCM(key_from(passphrase, salt)).decrypt(nonce, ciphertext, MAGIC)))
    except Exception:
        raise ValueError("Transfer passphrase or file is invalid") from None


def read_table(session, name):
    table = Base.metadata.tables[name]
    return [dict(row) for row in session.execute(select(table)).mappings()]


def approved_rows(session):
    rows = {name: read_table(session, name) for name in ORDER}
    current = [record for record in rows["source_records"] if record["canonical_type"] == "prescribed_set"
               and record["canonical_id"]]
    source_ids = {item["source_id"] for item in current}
    mapping_ids = {item["mapping_id"] for item in current}
    import_ids = {item["import_id"] for item in current}
    rows["source_records"] = current
    rows["record_revisions"] = [item for item in rows["record_revisions"]
                                if item["source_record_id"] in {record["source_record_id"] for record in current}]
    rows["data_sources"] = [item for item in rows["data_sources"] if item["source_id"] in source_ids]
    rows["mapping_profiles"] = [item for item in rows["mapping_profiles"] if item["mapping_id"] in mapping_ids]
    rows["import_jobs"] = [item for item in rows["import_jobs"] if item["import_id"] in import_ids
                           and item["state"] == "completed"]
    if len(rows["import_jobs"]) != len(import_ids):
        raise ValueError("A canonical source refers to an unapproved import")
    for item in rows["data_sources"]:
        item["external_id"] = None
    for item in rows["import_jobs"]:
        item["preview_json"] = None
        item["snapshot_path"] = None
    return rows


def check_rows(rows):
    if set(rows) != set(ORDER):
        raise ValueError("Transfer schema does not match")
    ids = {item["athlete_id"] for item in rows["athletes"]}
    if any(item["athlete_id"] not in ids for item in rows["training_blocks"] + rows["data_sources"]):
        raise ValueError("Transfer has an unknown athlete")
    if any(item["canonical_id"] not in {planned["prescribed_set_id"] for planned in rows["prescribed_sets"]}
           for item in rows["source_records"]):
        raise ValueError("Transfer has an unknown set reference")
    return {name: len(rows[name]) for name in ORDER}


def export_file(destination: Path, passphrase: str):
    if destination.exists():
        raise FileExistsError("Transfer destination already exists")
    with SessionLocal() as session:
        rows = approved_rows(session)
    counts = check_rows(rows)
    content = seal({"version": 1, "counts": counts, "rows": rows}, passphrase)
    with destination.open("xb") as output:
        output.write(content)
    return counts


def import_file(source: Path, passphrase: str, confirmed: bool = False):
    payload = unseal(source.read_bytes(), passphrase)
    if payload.get("version") != 1 or payload.get("counts") != check_rows(payload.get("rows", {})):
        raise ValueError("Transfer counts or version do not match")
    if not confirmed:
        return payload["counts"]
    with SessionLocal.begin() as session:
        if session.execute(select(Base.metadata.tables["athletes"].c.athlete_id).limit(1)).first():
            raise ValueError("Hosted database already has athletes; import requires a fresh workspace")
        for name in ORDER:
            if payload["rows"][name]:
                session.execute(Base.metadata.tables[name].insert(), payload["rows"][name])
    return payload["counts"]


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in {"export", "import"}:
        raise SystemExit("Usage: python -m strengthos.transfer export|import PATH")
    action, path = sys.argv[1], Path(sys.argv[2])
    if action == "export" and os.environ.get("STRENGTHOS_DATABASE_URL"):
        raise SystemExit("Export must run against the local encrypted workspace")
    if action == "import" and not os.environ.get("STRENGTHOS_DATABASE_URL"):
        raise SystemExit("Import requires a hosted STRENGTHOS_DATABASE_URL")
    passphrase = getpass("Transfer passphrase: ")
    if action == "export":
        counts = export_file(path, passphrase)
        print("Encrypted export created. Review counts before transferring:", counts)
    else:
        counts = import_file(path, passphrase)
        print("Review the transfer counts:", counts)
        if input("Type IMPORT to write to the hosted database: ").strip() != "IMPORT":
            raise SystemExit("Import cancelled; no data written")
        import_file(path, passphrase, confirmed=True)
        print("Import complete. Verify athlete and set counts in the portal.")


if __name__ == "__main__":
    main()
