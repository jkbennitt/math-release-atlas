#!/usr/bin/env bash
# Build the atlas from this worktree and serve dist on the GitHub Pages base path.
set -euo pipefail

ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
PORT="${VERIFY_ATLAS_PORT:-4321}"
STATE="${VERIFY_ATLAS_STATE:-/tmp/verify-atlas-run}"
EVIDENCE="${VERIFY_ATLAS_EVIDENCE:-/tmp/verify-atlas-evidence}"
BASE="http://127.0.0.1:${PORT}/math-release-atlas/"

mkdir -p "$STATE" "$EVIDENCE"
cd "$ROOT"

if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "port ${PORT} is already in use; leave that process alone" >&2
  exit 1
fi

python3 -m pip install -r requirements.txt
npm ci
npm run build

git rev-parse HEAD | tee "$STATE/head" > "$EVIDENCE/head.txt"
git status --porcelain > "$STATE/status"
if [[ -s "$STATE/status" ]]; then
  echo "worktree is dirty after the build; the preview would not be this HEAD" >&2
  cat "$STATE/status" >&2
  exit 1
fi
sha256sum dist/index.html | awk '{print $1}' > "$STATE/index.sha"
date -u +%Y-%m-%dT%H:%M:%SZ | tee "$STATE/built_at" > "$EVIDENCE/built_at.txt"
echo "$PORT" > "$STATE/port"
echo "$ROOT" > "$STATE/root"

set -m
nohup npm run preview -- --host 127.0.0.1 --port "$PORT" > "$EVIDENCE/preview.log" 2>&1 &
pid=$!
disown "$pid" || true
echo "$pid" > "$STATE/pid"

ready=0
for _ in $(seq 1 60); do
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "preview exited before the home table was served" >&2
    cat "$EVIDENCE/preview.log" >&2
    exit 1
  fi
  if body="$(curl -fsS --max-time 2 "$BASE" 2>/dev/null)"; then
    if grep -q 'id="family-search"' <<<"$body" \
      && grep -q 'data-family-table' <<<"$body" \
      && grep -q '<title>Math Release Atlas</title>' <<<"$body"; then
      ready=1
      break
    fi
  fi
  sleep 1
done
if [[ "$ready" != 1 ]]; then
  echo "preview never served the home table at ${BASE}" >&2
  cat "$EVIDENCE/preview.log" >&2
  exit 1
fi
echo "ready ${BASE}"
