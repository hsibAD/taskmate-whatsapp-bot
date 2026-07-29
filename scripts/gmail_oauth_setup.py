"""Authorize the bot mailbox and save an encrypted Gmail OAuth token."""

import argparse
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from dotenv import load_dotenv

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]


def arguments() -> argparse.Namespace:
    load_dotenv()
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--credentials",
        type=Path,
        default=Path("secrets/google-oauth.json"),
        help="Downloaded OAuth Desktop client JSON",
    )
    parser.add_argument(
        "--token",
        type=Path,
        default=Path("secrets/google-oauth.json.token"),
        help="Encrypted token output path",
    )
    parser.add_argument(
        "--fernet-key",
        default=os.getenv("GMAIL_TOKEN_ENCRYPTION_KEY"),
        help="Fernet key; defaults to GMAIL_TOKEN_ENCRYPTION_KEY",
    )
    return parser.parse_args()


def main() -> None:
    args = arguments()
    if not args.credentials.exists():
        raise SystemExit(f"OAuth client file not found: {args.credentials}")
    key = args.fernet_key
    if not key:
        generated = Fernet.generate_key().decode()
        raise SystemExit(
            "GMAIL_TOKEN_ENCRYPTION_KEY is not set.\n"
            f"Add this line to .env, then rerun the command:\n"
            f"GMAIL_TOKEN_ENCRYPTION_KEY={generated}"
        )
    try:
        cipher = Fernet(key.encode())
    except (TypeError, ValueError) as exc:
        raise SystemExit("GMAIL_TOKEN_ENCRYPTION_KEY is not a valid Fernet key") from exc

    flow = InstalledAppFlow.from_client_secrets_file(str(args.credentials), SCOPES)
    credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
    service = build("gmail", "v1", credentials=credentials, cache_discovery=False)
    profile = service.users().getProfile(userId="me").execute()

    args.token.parent.mkdir(parents=True, exist_ok=True)
    args.token.write_bytes(cipher.encrypt(credentials.to_json().encode()))
    args.token.chmod(0o600)
    print(
        json.dumps(
            {
                "authorized_mailbox": profile["emailAddress"],
                "encrypted_token": str(args.token),
                "scopes": SCOPES,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
