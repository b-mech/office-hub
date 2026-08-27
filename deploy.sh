#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/home/officehub/office-hub"
BRANCH="feature/docusign"
PUBLIC_URL="https://officehub.n10z.ca"

echo "========================================"
echo " Office Hub Production Deployment"
echo "========================================"

cd "$ROOT"

# Get sudo authentication before starting.
sudo -v

# Do not overwrite tracked production changes.
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
    echo
    echo "ERROR: Production has uncommitted tracked changes:"
    git status --short
    echo
    echo "Deployment cancelled."
    exit 1
fi

CURRENT_BRANCH="$(git branch --show-current)"

if [[ "$CURRENT_BRANCH" != "$BRANCH" ]]; then
    echo "ERROR: Expected branch $BRANCH but currently on $CURRENT_BRANCH"
    exit 1
fi

OLD_SHA="$(git rev-parse --short HEAD)"

echo
echo "1/7  Updating code from GitHub..."
git fetch origin "$BRANCH"
git pull --ff-only origin "$BRANCH"

NEW_SHA="$(git rev-parse --short HEAD)"

echo "Previous: $OLD_SHA"
echo "Current:  $NEW_SHA"

echo
echo "2/7  Installing backend dependencies..."
cd "$ROOT/backend"
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m pip check
deactivate

echo
echo "3/7  Installing frontend dependencies..."
cd "$ROOT/frontend"
npm ci

echo
echo "4/7  Building frontend..."
cd "$ROOT"
set -a
source .env
set +a

cd "$ROOT/frontend"
rm -rf .next
npm run build

echo
echo "5/7  Restarting Office Hub..."
sudo systemctl restart officehub-backend
sudo systemctl restart officehub-frontend

echo
echo "6/7  Checking infrastructure..."

for container in \
    office-hub-postgres-1 \
    office-hub-minio-1 \
    office-hub-redis-1
do
    if ! docker ps --format '{{.Names}}' | grep -qx "$container"; then
        echo "ERROR: $container is not running."
        exit 1
    fi
done

for service in officehub-backend officehub-frontend cloudflared
do
    if ! systemctl is-active --quiet "$service"; then
        echo "ERROR: $service is not running."
        systemctl --no-pager --full status "$service" || true
        exit 1
    fi
done

echo
echo "7/7  Running health checks..."

# Give systemd a moment to initialize the processes.
for attempt in {1..10}; do
    if curl -fsS http://127.0.0.1:8000/health >/dev/null; then
        break
    fi

    if [[ "$attempt" == "10" ]]; then
        echo "ERROR: Backend health check failed."
        sudo journalctl -u officehub-backend -n 40 --no-pager
        exit 1
    fi

    sleep 1
done

if ! curl -fsSI http://127.0.0.1:3000 >/dev/null; then
    echo "ERROR: Frontend health check failed."
    sudo journalctl -u officehub-frontend -n 40 --no-pager
    exit 1
fi

echo
echo "Local backend:   PASS"
echo "Local frontend:  PASS"
echo "Docker services: PASS"
echo "System services: PASS"

if curl -fsSI --max-time 15 "$PUBLIC_URL" >/dev/null; then
    echo "Public site:     PASS"
else
    echo "Public site:     WARNING - external check failed"
    echo "                 Check $PUBLIC_URL manually."
fi

echo
echo "========================================"
echo " DEPLOYMENT COMPLETE"
echo " Commit: $NEW_SHA"
echo " $PUBLIC_URL"
echo "========================================"
