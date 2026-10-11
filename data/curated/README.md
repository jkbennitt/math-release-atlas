# Curated notes

The generator writes `data/upstream.json` only. It never edits this directory.

Add one `NNN.yaml` file per family that needs a hand-written note. AlphaProof
and Anthropic lens tags live in `alphaproof.yaml` and `anthropic.yaml`, keyed
by record id. Each of those tags has a why and an https source at the pinned
commit. The vocabulary for community
status lives in `community-status.yaml`. A status other than `claimed` needs an http(s) evidence
URL, a date, a short neutral note, and a matching entry in `status-approvals.yaml`. The entry
also pins that date and note. The allowlist starts empty. The family files in this catalogue
use `claimed`. See `CONTRIBUTING.md` for the pull-request steps. Status changes must be
approved by Jason (repo policy).
