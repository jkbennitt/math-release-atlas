#!/usr/bin/env bash
# Read-only check that the preview is this run, this HEAD, and the guard command passes.
set -euo pipefail

ROOT_FALLBACK="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
STATE="${VERIFY_ATLAS_STATE:-/tmp/verify-atlas-run}"
EVIDENCE="${VERIFY_ATLAS_EVIDENCE:-/tmp/verify-atlas-evidence}"
PORT="$(cat "$STATE/port")"
ROOT="$(cat "$STATE/root")"
PID="$(cat "$STATE/pid")"
HEAD="$(cat "$STATE/head")"
BASE="http://127.0.0.1:${PORT}/math-release-atlas/"

mkdir -p "$EVIDENCE"
if [[ "$ROOT" != "$ROOT_FALLBACK" ]]; then
  echo "state root ${ROOT} is not ${ROOT_FALLBACK}" >&2
  exit 1
fi
if ! kill -0 "$PID" 2>/dev/null; then
  echo "preview pid ${PID} is not running" >&2
  exit 1
fi

now="$(git -C "$ROOT" rev-parse HEAD)"
if [[ "$now" != "$HEAD" ]]; then
  echo "HEAD is ${now}, preview was built at ${HEAD}" >&2
  exit 1
fi
now_status="$(git -C "$ROOT" status --porcelain)"
if [[ "$now_status" != "$(cat "$STATE/status")" ]]; then
  echo "worktree changed after the build" >&2
  exit 1
fi
if [[ -n "$now_status" ]]; then
  echo "worktree is dirty; the preview is not the committed HEAD" >&2
  exit 1
fi
now_sha="$(sha256sum "$ROOT/dist/index.html" | awk '{print $1}')"
if [[ "$now_sha" != "$(cat "$STATE/index.sha")" ]]; then
  echo "dist/index.html changed after launch" >&2
  exit 1
fi

mapfile -t listeners < <(lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -Fp 2>/dev/null | sed -n 's/^p//p')
if [[ "${#listeners[@]}" -eq 0 ]]; then
  echo "nothing is listening on port ${PORT}" >&2
  exit 1
fi

is_descendant() {
  local pid="$1"
  local root="$2"
  local guard=0
  while [[ -n "$pid" && "$pid" != "0" && "$pid" != "1" && "$guard" -lt 40 ]]; do
    if [[ "$pid" == "$root" ]]; then
      return 0
    fi
    pid="$(ps -o ppid= -p "$pid" | tr -d ' ')"
    guard=$((guard + 1))
  done
  [[ "$pid" == "$root" ]]
}

for listener in "${listeners[@]}"; do
  if ! is_descendant "$listener" "$PID"; then
    echo "port ${PORT} is owned by pid ${listener}, not preview pid ${PID}" >&2
    exit 1
  fi
  cwd="$(readlink -f "/proc/${listener}/cwd")"
  if [[ "$cwd" != "$ROOT" ]]; then
    echo "listener ${listener} cwd is ${cwd}" >&2
    exit 1
  fi
done

curl -fsS --max-time 10 "$BASE" -o "$EVIDENCE/doctor-home.html"
if ! cmp -s "$EVIDENCE/doctor-home.html" "$ROOT/dist/index.html"; then
  echo "preview is not serving dist/index.html" >&2
  exit 1
fi
if ! grep -q 'id="family-search"' "$EVIDENCE/doctor-home.html" \
  || ! grep -q 'data-family-table' "$EVIDENCE/doctor-home.html"; then
  echo "home response is not the atlas table" >&2
  exit 1
fi

# --verify-upstream sparse-fetches the pinned upstream commits and needs a network.
cd "$ROOT"
set +e
python3 scripts/check.py --self-test --source --verify-upstream > "$EVIDENCE/check-py.txt" 2>&1
code=$?
set -e
cat "$EVIDENCE/check-py.txt"
if [[ "$code" -ne 0 ]]; then
  echo "check.py exited ${code}" >&2
  exit "$code"
fi
echo "doctor passed"
