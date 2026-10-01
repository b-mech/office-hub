from __future__ import annotations

import json
import os

from google_auth_oauthlib.flow import InstalledAppFlow

from app.core.config import settings
from app.services.rental_inspection_reports import GOOGLE_SCOPES


def main() -> None:
    client_path = os.path.expanduser(settings.google_oauth_client_secret_path)
    token_path = os.path.expanduser(settings.google_oauth_token_path)
    if client_path and os.path.exists(client_path):
        flow = InstalledAppFlow.from_client_secrets_file(client_path, GOOGLE_SCOPES)
    elif token_path and os.path.exists(token_path):
        with open(token_path, encoding="utf-8") as token_file:
            existing = json.load(token_file)
        client_id = existing.get("client_id")
        client_secret = existing.get("client_secret")
        if not client_id or not client_secret:
            raise SystemExit("Google OAuth client configuration is missing")
        flow = InstalledAppFlow.from_client_config(
            {
                "installed": {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": existing.get("token_uri") or "https://oauth2.googleapis.com/token",
                    "redirect_uris": ["http://localhost"],
                }
            },
            GOOGLE_SCOPES,
        )
    else:
        raise SystemExit("Google OAuth client configuration is missing")
    open_browser = os.environ.get("GOOGLE_OAUTH_NO_BROWSER") != "1"
    credentials = flow.run_local_server(port=0, open_browser=open_browser, prompt="consent")
    os.makedirs(os.path.dirname(token_path), exist_ok=True)
    with open(token_path, "w", encoding="utf-8") as token_file:
        token_file.write(credentials.to_json())
    print("Google Workspace authorization saved with Sheets read, Gmail send, and Gmail compose scopes.")


if __name__ == "__main__":
    main()
