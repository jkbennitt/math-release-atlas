#!/usr/bin/env bash
# Install pinned Chrome for Testing 157 for the citation-graph check.
# The binary lands at /tmp/chrome157/chrome-linux64/chrome, which
# scripts/graph_a11y_check.mjs launches unless GRAPH_CHROME is set.
set -euo pipefail

VERSION="157.0.8103.15"
SHA256="ab9dd0ba103be79cc602962d8b21e285f26731a5115c1a759a0814da1346b54d"
URL="https://storage.googleapis.com/chrome-for-testing-public/157.0.8103.15/linux64/chrome-linux64.zip"
PREFIX="${GRAPH_CHROME_PREFIX:-/tmp/chrome157}"
BIN="${PREFIX}/chrome-linux64/chrome"
# zipfile.extractall does not keep the Unix mode bits. Chrome aborts if
# chrome_crashpad_handler is not executable.
mark_exec() {
  local path
  for path in \
    "${PREFIX}/chrome-linux64/chrome" \
    "${PREFIX}/chrome-linux64/chrome_crashpad_handler" \
    "${PREFIX}/chrome-linux64/chrome_sandbox" \
    "${PREFIX}/chrome-linux64/chrome-wrapper"
  do
    if [[ -e "$path" ]]; then
      chmod a+x "$path"
    fi
  done
}

helpers_ready() {
  [[ -x "${PREFIX}/chrome-linux64/chrome" ]] \
    && [[ -x "${PREFIX}/chrome-linux64/chrome_crashpad_handler" ]] \
    && [[ -x "${PREFIX}/chrome-linux64/chrome_sandbox" ]] \
    && [[ -x "${PREFIX}/chrome-linux64/chrome-wrapper" ]]
}

mark_exec
if helpers_ready; then
  got="$("$BIN" --version 2>/dev/null || true)"
  if [[ "$got" == *"$VERSION"* ]]; then
    echo "Chrome for Testing ${VERSION} is at ${BIN}"
    exit 0
  fi
fi

tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT
curl -fsSL "$URL" -o "$tmpdir/chrome.zip"
python3 - "$tmpdir/chrome.zip" "$SHA256" <<'PY'
import hashlib
import pathlib
import sys

path, expected = sys.argv[1], sys.argv[2]
digest = hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
if digest != expected:
    raise SystemExit(f"chrome zip sha256 {digest} != {expected}")
print(f"chrome zip sha256 {digest}")
PY
mkdir -p "$PREFIX"
python3 - "$tmpdir/chrome.zip" "$PREFIX" <<'PY'
import os
import sys
import zipfile

archive = zipfile.ZipFile(sys.argv[1])
dest = sys.argv[2]
for info in archive.infolist():
    rel = info.filename
    if rel.startswith("/") or ".." in rel.split("/"):
        raise SystemExit(f"refusing zip path {rel}")
archive.extractall(dest)
for info in archive.infolist():
    mode = (info.external_attr >> 16) & 0o7777
    if mode == 0:
        continue
    rel = info.filename
    path = os.path.join(dest, rel)
    if os.path.lexists(path):
        os.chmod(path, mode)
PY
mark_exec
if ! helpers_ready; then
  echo "Chrome for Testing ${VERSION} is missing an executable helper" >&2
  exit 1
fi
"$BIN" --version
