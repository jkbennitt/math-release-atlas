# Contributing

## Community status

Status changes are pull requests. Jason approves each change. The weekly sync does not edit
`data/curated/` and does not choose a status.

Open a pull request that edits `data/curated/NNN.yaml` for that family. The allowed ids are
listed in `data/curated/community-status.yaml`:

- `claimed`
- `community-checking`
- `independently-checked`
- `disputed`
- `retracted`

For any status other than `claimed`, add an `evidence` item with:

- `url`: an http or https URL, with no spaces, quotes, or angle brackets
- `date`: `YYYY-MM-DD`
- `note`: a short neutral note, at most 25 words

Optional `history` entries use the same fields. A history entry whose status is not `claimed`
also needs a URL.

A status other than `claimed` passes Guard only when `data/curated/status-approvals.yaml`
has a matching entry. Each entry lists `id`, `status`, `url`, and `approver`. The approver
is `jkbennitt`. The URL is the same evidence URL. A history entry that is not `claimed`
needs its own entry. The allowlist starts empty, so adding one is a separate, visible diff.
`.github/CODEOWNERS` assigns `data/curated/**` and the allowlist file to @jkbennitt.

Keep the note descriptive and neutral. The build rejects a hostile note, and it rejects a
note that pairs a guarded problem name with a claim verb. The generator copies the curated
status onto the family record. It does not invent one.
