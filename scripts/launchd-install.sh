#!/bin/bash
set -euo pipefail

ROOT="/Users/nicholastenszen/dev/office-hub"
ENV_FILE="${ROOT}/.env"
PLIST_NAME="com.officehub.backend.plist"
TARGET_DIR="${HOME}/Library/LaunchAgents"
TARGET_PLIST="${TARGET_DIR}/${PLIST_NAME}"
TMP_PLIST="$(mktemp "/tmp/${PLIST_NAME}.XXXXXX")"
LOAD_PLIST="true"

if [[ "${1:-}" == "--no-load" ]]; then
  LOAD_PLIST="false"
fi

escape_xml() {
  local value="$1"
  value="${value//&/&amp;}"
  value="${value//</&lt;}"
  value="${value//>/&gt;}"
  value="${value//\"/&quot;}"
  printf '%s' "$value"
}

write_environment() {
  while IFS= read -r line || [[ -n "$line" ]]; do
    [[ -z "$line" || "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" != *=* ]] && continue

    local key="${line%%=*}"
    local value="${line#*=}"
    key="$(escape_xml "$key")"
    value="$(escape_xml "$value")"

    printf '    <key>%s</key>\n' "$key"
    printf '    <string>%s</string>\n' "$value"
  done < "$ENV_FILE"
}

mkdir -p "$TARGET_DIR"

{
  cat <<'PLIST_HEADER'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.officehub.backend</string>

  <key>ProgramArguments</key>
  <array>
    <string>/Users/nicholastenszen/dev/office-hub/backend/.venv/bin/uvicorn</string>
    <string>app.main:app</string>
    <string>--host</string>
    <string>127.0.0.1</string>
    <string>--port</string>
    <string>8000</string>
  </array>

  <key>WorkingDirectory</key>
  <string>/Users/nicholastenszen/dev/office-hub/backend</string>

  <key>EnvironmentVariables</key>
  <dict>
PLIST_HEADER
  write_environment
  cat <<'PLIST_FOOTER'
  </dict>

  <key>KeepAlive</key>
  <true/>

  <key>RunAtLoad</key>
  <true/>

  <key>StandardOutPath</key>
  <string>/tmp/officehub-backend.log</string>

  <key>StandardErrorPath</key>
  <string>/tmp/officehub-backend-error.log</string>
</dict>
</plist>
PLIST_FOOTER
} > "$TMP_PLIST"

cp "$TMP_PLIST" "$TARGET_PLIST"
rm -f "$TMP_PLIST"

if [[ "$LOAD_PLIST" == "true" ]]; then
  launchctl load "$TARGET_PLIST"
  echo "Installed and loaded ${PLIST_NAME}"
else
  echo "Installed ${PLIST_NAME} without loading"
fi
