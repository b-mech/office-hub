from __future__ import annotations

import os

from google_auth_oauthlib.flow import InstalledAppFlow

from app.core.config import settings
from app.services.rental_inspection_reports import GOOGLE_SCOPES


def main() -> None:
    client_path = os.path.expanduser(settings.google_oauth_client_secret_path)
    token_path = os.path.expanduser(settings.google_oauth_token_path)
    if not client_path or not os.path.exists(client_path):
        raise SystemExit("GOOGLE_OAUTH_CLIENT_SECRET_PATH is not configured")
    flow = InstalledAppFlow.from_client_secrets_file(client_path, GOOGLE_SCOPES)
    credentials = flow.run_local_server(port=0, open_browser=True, prompt="consent")
    os.makedirs(os.path.dirname(token_path), exist_ok=True)
    with open(token_path, "w", encoding="utf-8") as token_file:
        token_file.write(credentials.to_json())
    print("Google Workspace authorization saved with Sheets read and Gmail send scopes.")


if __name__ == "__main__":
    main()
