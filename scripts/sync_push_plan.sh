#!/bin/bash
# Decide whether to update the open bot sync branch or open a fresh one.
# Commits already on origin/main are not edits of the sync branch.
# Usage: sync_push_plan.sh <open-branch> <pr-number> <new-sha>
set -euo pipefail

existing="${1:?branch}"
number="${2:-}"
new_sha="${3:?sha}"
if [ "${#new_sha}" -lt 12 ]; then
  echo "new sha is too short" >&2
  exit 1
fi

human=false
while IFS=$'\t' read -r name email committer committer_email; do
  [ -z "${name}" ] && continue
  if [ "$name" != "github-actions[bot]" ] \
    || [ "$email" != "41898282+github-actions[bot]@users.noreply.github.com" ] \
    || [ "$committer" != "github-actions[bot]" ] \
    || [ "$committer_email" != "41898282+github-actions[bot]@users.noreply.github.com" ]; then
    human=true
    break
  fi
done < <(git log --format='%an%x09%ae%x09%cn%x09%ce' origin/main..sync-existing)

if [ "$human" = true ]; then
  printf 'mode=fresh\nbranch=upstream-sync-%s\nnumber=\n' "${new_sha:0:12}"
else
  printf 'mode=reuse\nbranch=%s\nnumber=%s\n' "$existing" "$number"
fi
