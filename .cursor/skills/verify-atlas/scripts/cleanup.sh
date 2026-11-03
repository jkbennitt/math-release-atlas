#!/usr/bin/env bash
# Stop the preview this run started. Evidence files are left in place.
set -euo pipefail

STATE="${VERIFY_ATLAS_STATE:-/tmp/verify-atlas-run}"
EVIDENCE="${VERIFY_ATLAS_EVIDENCE:-/tmp/verify-atlas-evidence}"
PID="$(cat "$STATE/pid")"

if [[ ! "$PID" =~ ^[0-9]+$ ]] || [[ "$PID" -le 1 ]]; then
  echo "refusing to signal pid ${PID}" >&2
  exit 1
fi
if [[ ! -d "/proc/${PID}" ]]; then
  echo "preview pid ${PID} is already gone"
  echo "evidence remains at ${EVIDENCE}"
  exit 0
fi

cmd="$(tr '\0' ' ' < "/proc/${PID}/cmdline")"
case "$cmd" in
  *npm*|*astro*|*node*) ;;
  *)
    echo "recorded pid ${PID} cmdline is not the preview this run started: ${cmd}" >&2
    exit 1
    ;;
esac

kill_tree() {
  local parent="$1"
  local child
  for child in $(pgrep -P "$parent" || true); do
    kill_tree "$child"
  done
  kill -TERM "$parent" 2>/dev/null || true
}

kill_tree "$PID"
for _ in 1 2 3 4 5; do
  if [[ ! -d "/proc/${PID}" ]]; then
    break
  fi
  sleep 1
done
if [[ -d "/proc/${PID}" ]]; then
  kill_tree_kill() {
    local parent="$1"
    local child
    for child in $(pgrep -P "$parent" || true); do
      kill_tree_kill "$child"
    done
    kill -KILL "$parent" 2>/dev/null || true
  }
  kill_tree_kill "$PID"
fi
echo "stopped preview pid ${PID}"
echo "evidence remains at ${EVIDENCE}"
