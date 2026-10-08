# Contributing

## Community status

Status changes are pull requests. Jason approves each change. The weekly sync does not edit
`data/curated/` and does not choose a status.

Open a pull request that edits `data/curated/NNN.yaml` for that family. The allowed ids are
listed in `data/curated/community-status.yaml`:

- `claimed`
- `community-checking`
- `independently-verified`
- `disputed`
- `retracted`

For any status other than `claimed`, add an `evidence` item with:

- `url`: an http or https URL
- `date`: `YYYY-MM-DD`
- `note`: a short neutral note, at most 25 words

Optional `history` entries use the same fields. A history entry whose status is not `claimed`
also needs a URL.

Keep the note descriptive. The build rejects a note that pairs a guarded problem name with a
claim verb. The generator copies the curated status onto the family record. It does not invent
one.
