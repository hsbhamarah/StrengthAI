"""Store backend integration credentials in the coach's Windows Credential Manager."""
import argparse
from getpass import getpass

import win32cred


def target(service):
    if not service.isascii() or not service.replace("-", "").isalnum() or len(service) > 60:
        raise ValueError("Use a short service name containing letters, numbers or hyphens")
    return "StrengthOS/" + service.lower()


def read_secret(service):
    record = win32cred.CredRead(target(service), win32cred.CRED_TYPE_GENERIC)
    return record["CredentialBlob"].decode("utf-16-le")


def store_secret(service, value):
    blob = value.encode("utf-16-le")
    if not blob or len(blob) > 2560:
        raise ValueError("Credential is empty or exceeds the Windows credential size limit")
    win32cred.CredWrite({
        "TargetName": target(service), "Type": win32cred.CRED_TYPE_GENERIC,
        "CredentialBlob": value, "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
    }, 0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("set", "remove"))
    parser.add_argument("service")
    args = parser.parse_args()
    if args.action == "set":
        store_secret(args.service, getpass("Integration secret: "))
    else:
        win32cred.CredDelete(target(args.service), win32cred.CRED_TYPE_GENERIC)
