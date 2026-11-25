"""First-run local coach account setup."""
from getpass import getpass
from pathlib import Path
from strengthos.storage import private_dir
import re
import json
import tempfile
import win32crypt
from argon2 import PasswordHasher


def normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Enter a valid coach email address")
    return email


def credentials(directory):
    path = directory / "coach.dpapi"
    if path.exists():
        raw = win32crypt.CryptUnprotectData(path.read_bytes(), None, None, None, 1)[1]
        return tuple(json.loads(raw))
    def legacy(name):
        path = directory / name
        return path.read_text(encoding="utf-8").strip() if path.exists() else None
    return legacy("coach_email.txt"), legacy("coach_password.hash")


def save_credentials(directory, email, password_hash, replace=False):
    directory.mkdir(parents=True, exist_ok=True)
    sealed = win32crypt.CryptProtectData(json.dumps([email, password_hash]).encode(), "StrengthOS coach", None, None, None, 1)
    with tempfile.NamedTemporaryFile(dir=directory, delete=False) as tmp:
        tmp.write(sealed)
    pending = Path(tmp.name)
    try:
        if replace:
            pending.replace(directory / "coach.dpapi")
        else:
            pending.rename(directory / "coach.dpapi")
    finally:
        pending.unlink(missing_ok=True)


def create_coach(directory: Path, email: str, password: str) -> None:
    email = normalize_email(email)
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    if any(credentials(directory)):
        raise FileExistsError("Coach account already configured")
    save_credentials(directory, email, PasswordHasher().hash(password))


def main():
    directory = private_dir()
    from strengthos.storage import migrate
    if not directory.exists():
        migrate(Path(__file__).resolve().parents[1] / "data", directory)
    email, stored_hash = credentials(directory)
    if email:
        raise SystemExit("Coach email already configured")
    if stored_hash:
        try:
            PasswordHasher().verify(stored_hash, getpass("Current coach password: "))
        except Exception:
            raise SystemExit("Current coach password is incorrect") from None
    try:
        email = normalize_email(input("Coach email: "))
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
    if not stored_hash:
        password = getpass("New coach password: ")
        if len(password) < 12 or password != getpass("Confirm password: "):
            raise SystemExit("Passwords must match and contain at least 12 characters")
        create_coach(directory, email, password)
    else:
        save_credentials(directory, email, stored_hash, replace=True)
    print("Coach account configured")

if __name__ == "__main__":
    main()
