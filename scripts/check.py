#!/usr/bin/env python3
"""Fail the build on drifted counts, unsourced tags, or overclaims."""

from __future__ import annotations

import argparse
import ast
import copy
import inspect
import json
import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

import yaml

import alphaproof
import anthropic
import atlaslib
import og_card
from alphaproof import (
    ALPHAPROOF_JSON,
    SOURCES_JSON,
    assert_alphaproof,
    assert_cross_source,
    catalogue_extras,
    verify_recorded_alphaproof,
)
from anthropic import (
    ANTHROPIC_JSON,
    assert_anthropic,
    verify_recorded_anthropic,
)
from atlaslib import (
    CAUTIONS_JSON,
    COMMUNITY_STATUSES,
    COMMUNITY_STATUS_FILE,
    CURATED_DIR,
    FAMILIES_JSON,
    REQUIRED_CAUTIONS,
    ROOT,
    UPSTREAM_JSON,
    AtlasError,
    assert_counts,
    attach_citations,
    check_authored,
    check_dist,
    check_preview_source,
    check_social_preview,
    denylist_hit,
    bare_result_claims,
    exempt_upstream_text,
    assert_merged_catalogue,
    assert_sha_is_ancestor,
    assert_upstream_digest,
    ensure_ancestor_of_origin_head,
    approval_mismatches,
    exempt_index_rows,
    load_cautions,
    load_community_schema,
    check_math_lens_sources,
    load_curated,
    load_status_approvals,
    parse_catalogue_lens,
    _href_is_pinned,
    materialize_upstream,
    merge_data,
    parse_contents,
    parse_slug_date,
    plainify,
    png_dimensions,
    preview_alt,
    published_prefix,
    read_json,
    require_upstream_ancestor,
    run_git,
    scan_overclaims,
    strip_upstream_quotes,
    validate_curated_file,
    verify_recorded_upstream,
)
from sync import resolve_remote_sha


def check_source() -> list[str]:
    failures: list[str] = []
    if not UPSTREAM_JSON.is_file() or not FAMILIES_JSON.is_file():
        return ["generated data files are missing"]
    try:
        cautions = load_cautions(CAUTIONS_JSON)
        curated = load_curated(CURATED_DIR)
        upstream = read_json(UPSTREAM_JSON)
        families = read_json(FAMILIES_JSON)
        alphaproof_payload = read_json(ALPHAPROOF_JSON)
        anthropic_payload = read_json(ANTHROPIC_JSON)
        extras = catalogue_extras(upstream, alphaproof_payload, anthropic_payload)
        assert_counts(upstream)
        assert_upstream_digest(upstream)
        assert_counts(families)
        assert_alphaproof(alphaproof_payload)
        assert_anthropic(anthropic_payload)
        assert_cross_source(
            upstream["upstream"]["commit"],
            alphaproof_payload["source"]["commit"],
            upstream["families"],
            alphaproof_payload["records"],
            families["cross"],
        )
        if read_json(SOURCES_JSON) != extras["sources"]:
            raise AtlasError("sources.json does not match the source registry")
        assert_merged_catalogue(upstream, families, curated, cautions, extras)
    except AtlasError as exc:
        failures.append(str(exc))
        failures.extend(check_authored())
        return failures
    for item in curated.values():
        for lens in item["lenses"]:
            if not lens["source"].strip():
                failures.append(f"{item['id']} lens {lens['tag']} is missing a source")
    failures.extend(check_math_lens_sources(families["families"]))
    failures.extend(check_status_vocabulary())
    failures.extend(check_status_approvals(curated))
    failures.extend(check_codeowners())
    failures.extend(check_sync_does_not_write_status())
    failures.extend(check_upstream_text_is_shown())
    failures.extend(check_authored())
    failures.extend(check_preview_source())
    return failures


def check_upstream_text_is_shown() -> list[str]:
    """Upstream summaries and manuscript titles stay on the page."""
    failures: list[str] = []
    for relative in (
        "src/pages/f/[id].astro",
        "src/pages/index.astro",
        "src/lib/atlas.ts",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        if "withheld" in text or "not shown on this page" in text:
            failures.append(f"{relative} hides upstream text")
    if "withheld" in (ROOT / "scripts" / "atlaslib.py").read_text(encoding="utf-8"):
        failures.append("scripts/atlaslib.py hides upstream text")
    if "withheld" in FAMILIES_JSON.read_text(encoding="utf-8"):
        failures.append("families.json hides upstream text")
    return failures


def check_status_approvals(curated: dict) -> list[str]:
    try:
        approvals = load_status_approvals(atlaslib.STATUS_APPROVALS_FILE)
    except AtlasError as exc:
        return [str(exc)]
    return approval_mismatches(curated, approvals)


def check_codeowners() -> list[str]:
    path = ROOT / ".github" / "CODEOWNERS"
    if not path.is_file():
        return ["CODEOWNERS is missing"]
    text = path.read_text(encoding="utf-8")
    failures: list[str] = []
    if "data/curated/**" not in text or "@jkbennitt" not in text:
        failures.append("CODEOWNERS does not assign data/curated to @jkbennitt")
    return failures


def check_status_vocabulary() -> list[str]:
    failures: list[str] = []
    try:
        load_community_schema(COMMUNITY_STATUS_FILE)
    except AtlasError as exc:
        failures.append(str(exc))
    lenses = (ROOT / "src" / "lib" / "lenses.ts").read_text(encoding="utf-8")
    for status in sorted(COMMUNITY_STATUSES):
        if f'"{status}"' not in lenses:
            failures.append(f"lenses.ts is missing community status {status}")
    for retired in ("community-confirmed", "broken"):
        if f'"{retired}"' in lenses:
            failures.append(f"lenses.ts still names retired status {retired}")
    return failures


def check_sync_does_not_write_status() -> list[str]:
    """The daily sync may refresh the catalogue. It must not author a community status."""
    sync = (ROOT / "scripts" / "sync.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "sync.yml").read_text(encoding="utf-8")
    failures: list[str] = []
    if "data/curated" in workflow:
        failures.append("sync workflow touches data/curated")
    if "git add data/upstream.json data/families.json" not in workflow:
        failures.append("sync workflow no longer limits the commit to generated catalogue files")
    if 'cron: "17 10 * * *"' not in workflow:
        failures.append("sync schedule is not daily at 10:17 UTC")
    if "0 13 * * 1" in workflow or 'cron: "0 ' in workflow:
        failures.append("sync cron is not the daily off-peak schedule")
    if "scripts/sync_pr_select.jq" not in workflow:
        failures.append("sync workflow does not use the pull request filter")
    if "pr list --head" in workflow:
        failures.append("sync workflow selects a pull request by branch name")
    if 'gh pr edit "$number"' not in workflow:
        failures.append("sync workflow does not edit a pull request by number")
    if "human commit" not in workflow or "upstream-sync-${NEW:0:12}" not in workflow:
        failures.append("sync workflow overwrites a human commit")
    if "--force-with-lease" not in workflow:
        failures.append("sync workflow lost its lease check for a bot branch")
    failures.extend(check_sync_pr_selection())
    advanced = check_sync_reuses_bot_pr_when_main_advances()
    if advanced:
        failures.append(advanced)
    missing_ref = check_sync_plan_fails_when_ref_missing()
    if missing_ref:
        failures.append(missing_ref)
    if "env -u GH_TOKEN -u GITHUB_TOKEN jq -e -f scripts/sync_pr_select.jq" not in workflow:
        failures.append("sync filter runs with the publish token set")
    if "env -u GH_TOKEN -u GITHUB_TOKEN bash scripts/sync_push_plan.sh" not in workflow:
        failures.append("sync push plan runs with the publish token set")
    if "pr merge" in workflow or "auto-merge" in workflow:
        failures.append("sync workflow merges a pull request")
    if "needs.prepare.outputs.code == '2' || needs.prepare.outputs.code == '3'" not in workflow:
        failures.append("sync publishes when the upstream commit is unchanged")
    if "\n  prepare:" not in workflow or "\n  publish:" not in workflow:
        failures.append("sync workflow lost the two-job split")
    if workflow.count("runs-on: ubuntu-latest") != 2 or "runs-on: self-hosted" in workflow:
        failures.append("sync workflow does not stay on two GitHub-hosted runners")
    for pin in (
        "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
        "actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065",
        "actions/setup-node@49933ea5288caeca8642d1e84afbd3f7d6820020",
        "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02",
        "actions/download-artifact@d3f86a106a0bac45b974a628896c90dbdf5c8093",
    ):
        if pin not in workflow:
            failures.append(f"sync workflow lost pin {pin}")
    if workflow.count("contents: read") != 2 or workflow.count("contents: write") != 1:
        failures.append("sync workflow changed contents permissions")
    if workflow.count("pull-requests: write") != 1:
        failures.append("sync workflow changed pull request permissions")
    if "actions: write" not in workflow:
        failures.append("sync workflow cannot start other workflows")
    if 'gh workflow run ci.yml --repo "$GITHUB_REPOSITORY" --ref "$BRANCH"' not in workflow:
        failures.append("sync workflow does not start Build on the sync branch")
    if 'gh workflow run guard.yml --repo "$GITHUB_REPOSITORY" --ref "$BRANCH"' not in workflow:
        failures.append("sync workflow does not start Guard on the sync branch")
    for name in ("ci.yml", "guard.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        if "workflow_dispatch:" not in text:
            failures.append(f"{name} is missing workflow_dispatch")
    if 'status == "unchanged"' not in sync and "Upstream commit is unchanged." not in sync:
        failures.append("sync.py does not exit cleanly when the commit is unchanged")
    if "return 0" not in sync:
        failures.append("sync.py does not exit cleanly when the commit is unchanged")
    for source, label in ((sync, "sync.py"), (workflow, "sync.yml")):
        if "community" in source:
            failures.append(f"{label} names community status")
        for status in sorted(COMMUNITY_STATUSES):
            if status in source:
                failures.append(f"{label} names community status {status}")
    return failures


def check_sync_pr_selection() -> list[str]:
    """The sync pull request filter ignores forks and human branches."""
    jq_path = ROOT / "scripts" / "sync_pr_select.jq"
    fixture_path = ROOT / "scripts" / "testdata" / "sync-prs.json"
    if not jq_path.is_file() or not fixture_path.is_file():
        return ["sync pull request filter is missing"]
    jq_text = jq_path.read_text(encoding="utf-8")
    failures: list[str] = []
    for required in ("isCrossRepository", "app/github-actions", "github-actions[bot]", "upstream-sync"):
        if required not in jq_text:
            failures.append(f"sync pull request filter is missing {required}")
    if "error(" not in jq_text:
        failures.append("sync pull request filter does not fail when more than one match exists")
    selected = subprocess.run(
        ["jq", "-e", "-f", str(jq_path), str(fixture_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if selected.returncode != 0:
        failures.append("sync pull request filter rejected the bot pull request")
        return failures
    try:
        chosen = json.loads(selected.stdout)
    except json.JSONDecodeError:
        failures.append("sync pull request filter did not return JSON")
        return failures
    if chosen != [{"number": 42, "headRefName": "upstream-sync"}]:
        failures.append("sync pull request filter kept a fork or a human branch")
    app_only = [
        {
            "number": 7,
            "isCrossRepository": False,
            "author": {"login": "app/github-actions", "is_bot": True},
            "headRefName": "upstream-sync-0123456789ab",
        }
    ]
    app_run = subprocess.run(
        ["jq", "-e", "-f", str(jq_path)],
        input=json.dumps(app_only),
        capture_output=True,
        text=True,
        check=False,
    )
    if app_run.returncode != 0 or json.loads(app_run.stdout) != [
        {"number": 7, "headRefName": "upstream-sync-0123456789ab"}
    ]:
        failures.append("sync pull request filter rejected the Actions app")
    doubled = json.loads(fixture_path.read_text(encoding="utf-8"))
    doubled.append(
        {
            "number": 43,
            "isCrossRepository": False,
            "author": {"login": "github-actions[bot]", "is_bot": True},
            "headRefName": "upstream-sync-abcdefabcdef",
        }
    )
    crowded = subprocess.run(
        ["jq", "-e", "-f", str(jq_path)],
        input=json.dumps(doubled),
        capture_output=True,
        text=True,
        check=False,
    )
    if crowded.returncode == 0:
        failures.append("sync pull request filter allowed more than one match")
    return failures


def check_sync_reuses_bot_pr_when_main_advances() -> str | None:
    """Main moving forward must not look like a human edit of the open bot pull request."""
    bot = "github-actions[bot]"
    bot_email = "41898282+github-actions[bot]@users.noreply.github.com"
    script = ROOT / "scripts" / "sync_push_plan.sh"
    if not script.is_file():
        return "sync push plan is missing"
    plan_text = script.read_text(encoding="utf-8")
    if "origin/main..sync-existing" not in plan_text:
        return "sync push plan does not compare against origin/main"
    workflow = (ROOT / ".github" / "workflows" / "sync.yml").read_text(encoding="utf-8")
    if "fetch-depth: 0" not in workflow or "scripts/sync_push_plan.sh" not in workflow:
        return "sync publish checkout does not fetch full history"
    if "refs/heads/main:refs/remotes/origin/main" not in workflow:
        return "sync publish job does not fetch origin/main"

    def commit(repo: Path, name: str, email: str, message: str, body: str) -> None:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
            "GIT_TERMINAL_PROMPT": "0",
        }
        (repo / "f").write_text(body, encoding="utf-8")
        subprocess.run(["git", "add", "f"], cwd=repo, env=env, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", message], cwd=repo, env=env, check=True, capture_output=True)

    with tempfile.TemporaryDirectory() as tmp:
        origin = Path(tmp) / "origin"
        shallow = Path(tmp) / "shallow"
        origin.mkdir()
        subprocess.run(["git", "init", "-b", "main", str(origin)], check=True, capture_output=True)
        commit(origin, "Ada", "ada@example.com", "main A", "a\n")
        subprocess.run(["git", "branch", "upstream-sync"], cwd=origin, check=True, capture_output=True)
        subprocess.run(["git", "checkout", "upstream-sync"], cwd=origin, check=True, capture_output=True)
        commit(origin, bot, bot_email, "bot B", "b\n")
        subprocess.run(["git", "checkout", "main"], cwd=origin, check=True, capture_output=True)
        commit(origin, "Ada", "ada@example.com", "main C", "c\n")
        subprocess.run(
            ["git", "clone", "--no-local", "--depth", "1", "--branch", "main", str(origin), str(shallow)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "fetch", "--no-tags", "origin", "upstream-sync:sync-existing"],
            cwd=shallow,
            check=True,
            capture_output=True,
        )
        shallow_log = subprocess.run(
            ["git", "log", "--format=%s", "HEAD..sync-existing"],
            cwd=shallow,
            check=True,
            capture_output=True,
            text=True,
        )
        if "main A" not in shallow_log.stdout.splitlines():
            return "shallow history did not reproduce the false human commit"
        subprocess.run(["git", "fetch", "--unshallow", "origin"], cwd=shallow, check=True, capture_output=True)
        reuse = subprocess.run(
            [
                "bash",
                str(script),
                "upstream-sync",
                "42",
                "abcdefabcdefabcdefabcdefabcdefabcdefabcd",
            ],
            cwd=shallow,
            check=True,
            capture_output=True,
            text=True,
        )
        if reuse.stdout != "mode=reuse\nbranch=upstream-sync\nnumber=42\n":
            return f"sync plan did not reuse the bot pull request: {reuse.stdout!r}"
        subprocess.run(["git", "checkout", "upstream-sync"], cwd=origin, check=True, capture_output=True)
        commit(origin, "Ada", "ada@example.com", "human D", "d\n")
        subprocess.run(
            ["git", "fetch", "--no-tags", "origin", "+upstream-sync:sync-existing"],
            cwd=shallow,
            check=True,
            capture_output=True,
        )
        fresh = subprocess.run(
            [
                "bash",
                str(script),
                "upstream-sync",
                "42",
                "0123456789abcdef0123456789abcdef01234567",
            ],
            cwd=shallow,
            check=True,
            capture_output=True,
            text=True,
        )
        if fresh.stdout != "mode=fresh\nbranch=upstream-sync-0123456789ab\nnumber=\n":
            return f"sync plan reused a branch with a human commit: {fresh.stdout!r}"
    return None


def check_sync_plan_fails_when_ref_missing() -> str | None:
    """A missing origin/main or sync-existing ref must not fall through to reuse."""
    script = ROOT / "scripts" / "sync_push_plan.sh"
    plan_text = script.read_text(encoding="utf-8")
    if plan_text.count("git rev-parse --verify") < 2:
        return "sync push plan does not verify origin/main and sync-existing"
    if "< <(git log" in plan_text:
        return "sync push plan still ignores a failed git log"
    sha = "abcdefabcdefabcdefabcdefabcdefabcdefabcd"

    def run(repo: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(script), "upstream-sync", "42", sha],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )

    def commit_file(repo: Path) -> None:
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Ada",
            "GIT_AUTHOR_EMAIL": "ada@example.com",
            "GIT_COMMITTER_NAME": "Ada",
            "GIT_COMMITTER_EMAIL": "ada@example.com",
            "GIT_TERMINAL_PROMPT": "0",
        }
        (repo / "f").write_text("a\n", encoding="utf-8")
        subprocess.run(["git", "add", "f"], cwd=repo, env=env, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "seed"], cwd=repo, env=env, check=True, capture_output=True)

    with tempfile.TemporaryDirectory() as tmp:
        empty = Path(tmp) / "empty"
        empty.mkdir()
        subprocess.run(["git", "init", "-b", "main", str(empty)], check=True, capture_output=True)
        missing_both = run(empty)
        if missing_both.returncode == 0 or "mode=reuse" in missing_both.stdout:
            return "sync push plan reused a branch with no origin/main"

        only_main = Path(tmp) / "only-main"
        only_main.mkdir()
        subprocess.run(["git", "init", "-b", "main", str(only_main)], check=True, capture_output=True)
        commit_file(only_main)
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", "HEAD"],
            cwd=only_main,
            check=True,
            capture_output=True,
        )
        missing_sync = run(only_main)
        if missing_sync.returncode == 0 or "mode=reuse" in missing_sync.stdout:
            return "sync push plan reused a branch when sync-existing was missing"

        only_sync = Path(tmp) / "only-sync"
        only_sync.mkdir()
        subprocess.run(["git", "init", "-b", "main", str(only_sync)], check=True, capture_output=True)
        commit_file(only_sync)
        subprocess.run(
            ["git", "branch", "sync-existing"],
            cwd=only_sync,
            check=True,
            capture_output=True,
        )
        missing_main = run(only_sync)
        if missing_main.returncode == 0 or "mode=reuse" in missing_main.stdout:
            return "sync push plan reused a branch when origin/main was missing"
    return None


def _calls_named(func, name: str) -> bool:
    tree = ast.parse(inspect.getsource(func))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = node.func
        ident = called.id if isinstance(called, ast.Name) else called.attr if isinstance(called, ast.Attribute) else ""
        if ident == name:
            return True
    return False


def _git(repo: Path, *args: str) -> str:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "atlas",
        "GIT_AUTHOR_EMAIL": "atlas@example.com",
        "GIT_COMMITTER_NAME": "atlas",
        "GIT_COMMITTER_EMAIL": "atlas@example.com",
        "GIT_TERMINAL_PROMPT": "0",
    }
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def alphaproof_self_test() -> list[str]:
    """The AlphaProof parser counts files it can see and does not invent the rest."""
    failures: list[str] = []
    deposited = alphaproof.erdos_statement(741, "i", None)
    if bare_result_claims(deposited):
        failures.append("a deposited-file sentence was flagged")
    if not bare_result_claims("The agent solved Erdős #12."):
        failures.append("a bare solved claim was accepted")
    if not bare_result_claims("This proves the OEIS conjecture."):
        failures.append("a bare proves claim was accepted")
    quoted = f'<blockquote data-upstream="abstract">{alphaproof.ABSTRACT_CLAIM}</blockquote>'
    exempted = exempt_upstream_text(quoted, {alphaproof.ABSTRACT_CLAIM})
    if bare_result_claims(exempted):
        failures.append("an exact upstream quotation was flagged")
    if not bare_result_claims(quoted):
        failures.append("the same quotation was exempt outside the element")
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "APNOutputs" / "ErdosProblems").mkdir(parents=True)
        (repo / "APNOutputs" / "OEIS").mkdir(parents=True)
        (repo / "APNOutputs" / "AICollaborator" / "AlgebraicGeometry").mkdir(parents=True)
        (repo / "NaturalLanguageProofs" / "ErdosProblems").mkdir(parents=True)
        (repo / "NaturalLanguageProofs" / "AICollaborator").mkdir(parents=True)
        (repo / ".github" / "workflows").mkdir(parents=True)
        (repo / "APNOutputs" / "ErdosProblems" / "erdos_741.parts.i.lean").write_text("theorem\n", encoding="utf-8")
        (repo / "APNOutputs" / "ErdosProblems" / "erdos_26.variants.tenenbaum.lean").write_text("theorem\n", encoding="utf-8")
        (repo / "APNOutputs" / "OEIS" / "oeis_51293_conjecture_0.lean").write_text("theorem\n", encoding="utf-8")
        (repo / "APNOutputs" / "AICollaborator" / "AlgebraicGeometry" / "hilbert_functions_1.lean").write_text(
            "theorem\n", encoding="utf-8"
        )
        (repo / "NaturalLanguageProofs" / "ErdosProblems" / "erdos741i.pdf").write_bytes(b"%PDF")
        (repo / "NaturalLanguageProofs" / "ErdosProblems" / "erdos26.pdf").write_bytes(b"%PDF")
        (repo / "NaturalLanguageProofs" / "AICollaborator" / "hilbert.pdf").write_bytes(b"%PDF")
        (repo / "erdos_problems_attempted.txt").write_text("erdos_1\nerd os_2\n", encoding="utf-8")
        (repo / "lean-toolchain").write_text("leanprover/lean4:v4.27.0\n", encoding="utf-8")
        (repo / ".github" / "workflows" / "lean_action_ci.yml").write_text(
            "uses: leanprover/lean-action@v1\n", encoding="utf-8"
        )
        payload = alphaproof.build_alphaproof(repo, "b" * 40)
        counts = payload["counts"]
        if (counts["erdos"], counts["oeis_files"], counts["stacks"], counts["ai_collaborator"]) != (2, 1, 0, 1):
            failures.append(f"fixture counts were {counts}")
        if len(payload["records"]) != 4:
            failures.append("fixture invented or dropped a Lean file")
        by_anchor = {record["anchor"]: record for record in payload["records"]}
        row = by_anchor["erdos-741-part-i"]
        if not row["natural_language_proofs"] or "upper density" not in row["scope_notes"][0]:
            failures.append("741(i) lost its PDF or its scope note")
        if "solved" in row["statement"] or "proves" in row["statement"]:
            failures.append("741(i) statement overclaims")
        if by_anchor["erdos-26-variant-tenenbaum"]["scope_notes"][0].count("†") != 1:
            failures.append("26 lost the dagger scope note")
        if payload["gaps"][0]["label"] != "not in repo / unexplained" or payload["gaps"][0]["status"] != "PARTIAL":
            failures.append("OEIS gap label changed")
        if payload["gaps"][0]["absent"] != 43 or "missing_entries" in payload["gaps"][0]:
            failures.append("OEIS gap invented the absent files")
        attempted = payload["gaps"][1]
        if attempted["status"] != "PARTIAL" or attempted["label"] != "2 listed, 353 in paper":
            failures.append(f"attempted-count gap was not derived from the entries: {attempted}")
        matched = alphaproof.attempted_count_gap(353, 352)
        if matched["status"] != "MATCH" or matched["label"] != "353 listed, matching the paper":
            failures.append(f"a matching attempted list stayed partial: {matched}")
        oeis_labels = {
            38: "not in repo / unexplained",
            44: "44 files, matching the paper",
            45: "repo has 1 more file than paper",
            50: "repo has 6 more files than paper",
        }
        oeis_statuses = {38: "PARTIAL", 44: "MATCH", 45: "MORE THAN PAPER", 50: "MORE THAN PAPER"}
        for repo_files, status in oeis_statuses.items():
            gap = alphaproof.oeis_count_gap(repo_files)
            if gap["status"] != status or gap["absent"] != 44 - repo_files or gap["label"] != oeis_labels[repo_files]:
                failures.append(f"OEIS gap for {repo_files} files was {gap}")
            if status != "PARTIAL" and gap["label"] == "not in repo / unexplained":
                failures.append(f"OEIS label stayed on the absent wording for {status}")
            phrase = atlaslib.oeis_preview_phrase(repo_files, gap["paper_count"], gap["status"])
            if phrase != f"OEIS {repo_files} of 44 in paper ({status})":
                failures.append(f"preview phrase for {status} was {phrase}")
            preview = alphaproof.alphaproof_preview(
                {
                    "source": {"name": "AlphaProof Nexus", "org": "Google DeepMind"},
                    "counts": {
                        "lean_files": 71,
                        "oeis_files": repo_files,
                        "erdos": 9,
                        "stacks": 11,
                        "ai_collaborator": 13,
                    },
                    "gaps": [
                        gap,
                        {"id": "erdos-attempted", "status": "MATCH"},
                        {"id": "per-row-provenance", "status": "MISSING"},
                    ],
                }
            )
            entries = [
                {
                    "name": "OpenAI Math",
                    "org": "OpenAI",
                    "fragment": "372 result families and 719 manuscripts from the OpenAI Math catalogue",
                    "tiles": [
                        {"value": "372", "label": "result families"},
                        {"value": "719", "label": "manuscripts"},
                    ],
                    "detail": "",
                },
                {
                    "name": "AlphaProof Nexus",
                    "org": "Google DeepMind",
                    "fragment": preview["fragment"],
                    "tiles": preview["tiles"],
                    "detail": preview["detail"],
                },
            ]
            if phrase not in preview_alt(entries) or status not in preview_alt(entries):
                failures.append(f"alt text dropped {status}")
            if "MATCH" not in preview["fragment"] or "MISSING" not in preview["fragment"]:
                failures.append(f"AlphaProof preview dropped a status label: {preview['fragment']}")
            try:
                image = og_card.render(entries)
            except SystemExit as exc:
                failures.append(f"preview card rejected {status}: {exc}")
            else:
                if image.size != (atlaslib.PREVIEW_WIDTH, atlaslib.PREVIEW_HEIGHT):
                    failures.append(f"preview card for {status} is {image.size}")
        attempted_cases = (
            (2, 2, "PARTIAL", "2 listed, 353 in paper"),
            (353, 352, "MATCH", "353 listed, matching the paper"),
            (354, 354, "MORE THAN PAPER", "repo has 1 more entry than paper"),
            (360, 360, "MORE THAN PAPER", "repo has 7 more entries than paper"),
        )
        provenance_gap = {"id": "per-row-provenance", "status": "MISSING", "label": "per-row provenance"}
        for entries, newlines, status, label in attempted_cases:
            gap = alphaproof.attempted_count_gap(entries, newlines)
            if gap["status"] != status or gap["label"] != label or gap["repo_entries"] != entries:
                failures.append(f"attempted gap for {entries} entries was {gap}")
        pinned_oeis = alphaproof.oeis_count_gap(38)
        pinned_attempted = alphaproof.attempted_count_gap(353, 352)
        if pinned_oeis["label"] != "not in repo / unexplained" or pinned_oeis["absent"] != 6:
            failures.append(f"pinned OEIS gap moved: {pinned_oeis}")
        if pinned_attempted["label"] != "353 listed, matching the paper" or pinned_attempted["status"] != "MATCH":
            failures.append(f"pinned attempted gap moved: {pinned_attempted}")

        pinned_gaps = [pinned_oeis, pinned_attempted, provenance_gap]

        def rendered_gaps(oeis: dict, attempted: dict, provenance: dict) -> str:
            return atlaslib.render_alphaproof_gap_rows(
                {"oeis": oeis, "attempted": attempted, "provenance": provenance}
            )

        aligned = rendered_gaps(pinned_oeis, pinned_attempted, provenance_gap)
        if "The repository has no per-file agent record." not in aligned:
            failures.append("gap rows were not rendered from the AlphaProof page template")
        if atlaslib.check_gap_elements(aligned, pinned_gaps):
            failures.append(f"aligned gap rows failed: {atlaslib.check_gap_elements(aligned, pinned_gaps)}")
        swapped_badge = aligned.replace(
            '<span class="badge missing">MISSING</span>',
            '<span class="badge partial">PARTIAL</span>',
            1,
        )
        if ": MISSING" not in swapped_badge:
            failures.append("provenance fixture lost the repeated status")
        if not atlaslib.check_gap_elements(swapped_badge, pinned_gaps):
            failures.append("a swapped provenance badge passed because the row repeats : MISSING")
        template_cases = (
            (alphaproof.oeis_count_gap(44), pinned_attempted, provenance_gap),
            (alphaproof.oeis_count_gap(50), pinned_attempted, provenance_gap),
            (pinned_oeis, alphaproof.attempted_count_gap(354, 354), provenance_gap),
        )
        for oeis_gap, attempted_gap, provenance in template_cases:
            page = rendered_gaps(oeis_gap, attempted_gap, provenance)
            gaps = [oeis_gap, attempted_gap, provenance]
            problems = atlaslib.check_gap_elements(page, gaps)
            if problems:
                failures.append(f"template row for {oeis_gap['status']} / {attempted_gap['status']} failed: {problems}")
            for gap in (oeis_gap, attempted_gap):
                row = atlaslib._element_inner(page, f"gap-{gap['id']}")
                if row is None:
                    failures.append(f"template is missing gap-{gap['id']}")
                    continue
                if gap["status"] != "PARTIAL" and "Absent" in atlaslib._visible_text(row):
                    failures.append(f"the page template rendered Absent for {gap['status']}")
            if oeis_gap["status"] in ("MATCH", "MORE THAN PAPER") and f">{oeis_gap['status']}</span>" not in page:
                failures.append(f"template badge did not show {oeis_gap['status']}")
            if attempted_gap["status"] == "MORE THAN PAPER" and ">MORE THAN PAPER</span>" not in page:
                failures.append("template badge did not show MORE THAN PAPER for the attempted list")
        match_gap = alphaproof.oeis_count_gap(44)
        match_page = rendered_gaps(match_gap, pinned_attempted, provenance_gap)
        leaked = match_page.replace(
            f"Label: {match_gap['label']}.",
            f"Absent 0. Label: {match_gap['label']}.",
            1,
        )
        if "Absent 0." not in leaked or not atlaslib.check_gap_elements(
            leaked, [match_gap, pinned_attempted, provenance_gap]
        ):
            failures.append("Absent leak passed for a MATCH row rendered from the page template")
        social = (ROOT / "src" / "lib" / "social.ts").read_text(encoding="utf-8")
        if "source.preview.fragment" not in social:
            failures.append("social alt text does not render each source preview")
        badge_page = (ROOT / "src" / "pages" / "source" / "alphaproof-nexus.astro").read_text(encoding="utf-8")
        for status in ("PARTIAL", "MATCH", "MORE THAN PAPER"):
            if f'case "{status}":' not in badge_page:
                failures.append(f"source page badge does not handle {status}")
        if 'id={`gap-${oeis?.id}`}' not in badge_page or "oeis.absent > 0" not in badge_page:
            failures.append("source page does not key gap rows or gate Absent")
        page_check = inspect.getsource(atlaslib.check_alphaproof_pages)
        if '"PARTIAL"' in page_check:
            failures.append("AlphaProof page check still requires the literal PARTIAL")
        if "check_gap_elements" not in page_check:
            failures.append("AlphaProof page check does not scope statuses to gap rows")
        if any(record["provenance"] != "MISSING" for record in payload["records"]):
            failures.append("fixture assigned per-row provenance")
        families = [
            {"id": "021", "lean": {"comparators": [{"declarations": ["erdos_970_quadratic"]}]}},
            {"id": "100", "title": "The geometric case of the Erdős similarity conjecture"},
        ]
        joined = alphaproof.cross_source(families, payload["records"])
        if joined["shared"]:
            failures.append(f"titles or an unmatched number joined: {joined['shared']}")
        overlap = [
            {"id": "050", "lean": {"comparators": [{"declarations": ["erdos_741_main"]}]}},
        ]
        shared = alphaproof.cross_source(overlap, payload["records"])["shared"]
        if len(shared) != 1 or shared[0]["number"] != 741 or shared[0]["openai_families"] != ["050"]:
            failures.append(f"an explicit shared number was not joined: {shared}")
        rendered = """
        <ul id="shared-problems">
          <li>Erdős #741. OpenAI Math families 050. AlphaProof Nexus records APNOutputs/ErdosProblems/erdos_741.parts.i.lean.</li>
        </ul>
        <ul id="openai-numbers"><li>970: <a href="/f/021/">021</a></li><li>741: <a href="/f/050/">050</a></li></ul>
        <ul id="alphaproof-numbers"><li>741: 1 Lean file</li><li>26: 1 Lean file</li></ul>
        """
        page_join = {
            "shared": shared,
            "openai_numbers": [
                {"number": 970, "families": ["021"]},
                {"number": 741, "families": ["050"]},
            ],
            "alphaproof_numbers": [
                {"number": 741, "records": ["APNOutputs/ErdosProblems/erdos_741.parts.i.lean"]},
                {"number": 26, "records": ["APNOutputs/ErdosProblems/erdos_26.variants.tenenbaum.lean"]},
            ],
        }
        if atlaslib.check_cross_source_page(rendered, page_join):
            failures.append(f"a rendered non-empty join was rejected: {atlaslib.check_cross_source_page(rendered, page_join)}")
        hidden = rendered.replace(
            '<ul id="shared-problems">',
            '<p id="shared-problems">no shared problem ids at these commits</p><ul id="shared-problems">',
        )
        if not any("hides a non-empty join" in item for item in atlaslib.check_cross_source_page(hidden, page_join)):
            failures.append("a non-empty join labeled empty was accepted")
        elsewhere = rendered.replace(
            "Erdős #741. OpenAI Math families 050. AlphaProof Nexus records APNOutputs/ErdosProblems/erdos_741.parts.i.lean.",
            "Erdős #999. OpenAI Math families 050. AlphaProof Nexus records APNOutputs/ErdosProblems/erdos_741.parts.i.lean.",
        )
        if not any("does not render shared number 741" in item for item in atlaslib.check_cross_source_page(elsewhere, page_join)):
            failures.append("a shared number that appears only outside its list was accepted")
        wrong_count = rendered.replace("<li>741: 1 Lean file</li>", "<li>741: 9 Lean files</li>")
        if not any("741: 1 Lean file" in item for item in atlaslib.check_cross_source_page(wrong_count, page_join)):
            failures.append("a file count outside the alphaproof list satisfied the check")
        empty_page = """
        <p id="shared-problems">no shared problem ids at these commits</p>
        <ul id="openai-numbers"><li>970: <a href="/f/021/">021</a></li></ul>
        <ul id="alphaproof-numbers"><li>12: 1 Lean file</li></ul>
        """
        empty_join = {
            "shared": [],
            "openai_numbers": [{"number": 970, "families": ["021"]}],
            "alphaproof_numbers": [{"number": 12, "records": ["APNOutputs/ErdosProblems/erdos_12.lean"]}],
        }
        if atlaslib.check_cross_source_page(empty_page, empty_join):
            failures.append("an empty join with the empty sentence was rejected")
    recorded = read_json(ALPHAPROOF_JSON)
    if recorded["counts"]["erdos"] != 9 or recorded["counts"]["oeis_files"] != 38:
        failures.append("recorded AlphaProof counts are not the pinned file counts")
    if recorded["counts"]["stacks"] != 11 or recorded["counts"]["ai_collaborator"] != 13:
        failures.append("recorded Stacks or AI collaborator counts drifted")
    return failures


def ancestry_self_test() -> list[str]:
    """A commit that is not on origin HEAD fails the same check CI runs.

    The fixture is a local origin, so the negative case does not use the network.
    Guard still calls ensure_ancestor_of_origin_head, which fetches origin HEAD
    and runs git merge-base --is-ancestor.
    """
    failures: list[str] = []
    if not _calls_named(verify_recorded_upstream, "materialize_upstream"):
        failures.append("upstream verifier does not call materialize_upstream")
    if not _calls_named(materialize_upstream, "ensure_ancestor_of_origin_head"):
        failures.append("upstream verifier does not call the ancestry check")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        seed = root / "seed"
        seed.mkdir()
        _git(seed, "init", "-b", "main")
        (seed / "note").write_text("ancestor\n", encoding="utf-8")
        _git(seed, "add", "note")
        _git(seed, "commit", "-m", "ancestor")
        ancestor = _git(seed, "rev-parse", "HEAD")
        (seed / "note").write_text("head\n", encoding="utf-8")
        _git(seed, "add", "note")
        _git(seed, "commit", "-m", "head")
        head = _git(seed, "rev-parse", "HEAD")
        origin = root / "origin.git"
        _git(root, "clone", "--bare", str(seed), str(origin))
        other = root / "other"
        other.mkdir()
        _git(other, "init", "-b", "main")
        (other / "note").write_text("fork\n", encoding="utf-8")
        _git(other, "add", "note")
        _git(other, "commit", "-m", "fork")
        outsider = _git(other, "rev-parse", "HEAD")
        client = root / "client"
        _git(root, "clone", "--no-checkout", str(origin), str(client))
        _git(client, "remote", "add", "other", str(other))
        _git(client, "fetch", "other")
        try:
            ensure_ancestor_of_origin_head(client, outsider)
        except AtlasError as exc:
            if "not an ancestor" not in str(exc):
                failures.append(f"non-ancestor error was {exc}")
        else:
            failures.append("a non-ancestor commit was accepted")
        try:
            ensure_ancestor_of_origin_head(client, ancestor)
            ensure_ancestor_of_origin_head(client, head)
        except AtlasError as exc:
            failures.append(f"an ancestor of origin HEAD was rejected: {exc}")
        try:
            assert_sha_is_ancestor(client, outsider, "FETCH_HEAD")
        except AtlasError:
            pass
        else:
            failures.append("assert_sha_is_ancestor accepted a non-ancestor")
        try:
            require_upstream_ancestor(str(origin), outsider)
        except AtlasError as exc:
            if "not an ancestor" not in str(exc):
                failures.append(f"sync ancestry error was {exc}")
        else:
            failures.append("require_upstream_ancestor accepted a non-ancestor")
        try:
            require_upstream_ancestor(str(origin), ancestor)
        except AtlasError as exc:
            failures.append(f"require_upstream_ancestor rejected an ancestor: {exc}")
        missing = root / "missing.git"
        try:
            run_git(
                ["git", "clone", "--no-checkout", str(missing), str(root / "dest")],
                None,
                "could not fetch upstream",
            )
        except AtlasError as exc:
            message = str(exc)
            if "\n" in message or "Traceback" in message:
                failures.append(f"fetch failure was not one line: {message!r}")
        else:
            failures.append("a missing remote did not fail")
        try:
            resolve_remote_sha(str(root / "no-such.git"), None)
        except AtlasError as exc:
            message = str(exc)
            if "\n" in message or "Traceback" in message:
                failures.append(f"ls-remote failure was not one line: {message!r}")
        else:
            failures.append("ls-remote against a missing remote did not fail")
        called: list[str] = []
        original = atlaslib.ensure_ancestor_of_origin_head

        def spy(repo: Path, sha: str) -> None:
            called.append(sha)
            raise AtlasError("ancestry-check-called")

        atlaslib.ensure_ancestor_of_origin_head = spy
        try:
            try:
                materialize_upstream(str(origin), ancestor, root / "fresh")
            except AtlasError as exc:
                if "ancestry-check-called" not in str(exc):
                    failures.append(f"ancestry spy raised {exc}")
            else:
                failures.append("materialize_upstream returned without the ancestry check")
            if not called:
                failures.append("upstream verifier did not call the ancestry check")
        finally:
            atlaslib.ensure_ancestor_of_origin_head = original
    return failures


def anthropic_self_test() -> list[str]:
    """Identifier matching ignores camel-case fragments, and the formalization badge stays separate."""
    failures: list[str] = []
    missed = anthropic.find_identifiers("pseudoEisenstein")
    if any(missed[key] for key in ("erdos", "oeis", "stacks")):
        failures.append(f"pseudoEisenstein was treated as an identifier: {missed}")
    found = anthropic.find_identifiers(
        "pseudoEisenstein",
        "oeis_12",
        "A000042",
        "erdos_7",
        "https://stacks.math.columbia.edu/tag/00A1",
    )
    if found["oeis"] != ["000042", "12"] or found["erdos"] != ["7"]:
        failures.append(f"identifier scan dropped an explicit id: {found}")
    if "stacks.math.columbia" not in found["stacks"]:
        failures.append(f"identifier scan dropped a Stacks URL: {found}")
    empty = {
        "identifiers": {"erdos": [], "oeis": [], "stacks": [], "method": anthropic.IDENTIFIER_METHOD},
    }
    joined = anthropic.anthropic_join(empty, {741}, set(), "pseudoEisenstein erdos_741 oeis_12")
    if joined["shared_with_anthropic"] or joined["anthropic_empty_text"] != anthropic.ANTHROPIC_EMPTY_TEXT:
        failures.append(f"an empty Anthropic scan still joined: {joined}")
    overlap = {
        "identifiers": {"erdos": ["741"], "oeis": ["12"], "stacks": [], "method": anthropic.IDENTIFIER_METHOD},
    }
    shared = {
        (item["kind"], item["id"])
        for item in anthropic.anthropic_join(overlap, {741}, set(), "oeis_12")["shared_with_anthropic"]
    }
    if shared != {("erdos", "741"), ("oeis", "12")}:
        failures.append(f"Anthropic join missed an explicit id: {shared}")
    classified = anthropic.classify_flt(
        [
            "Theorems/Thm_a.lean",
            "P2M/Sol/a.lean",
            "P2M/Util.lean",
            "Definitions/d.lean",
            "FinalCheck.lean",
            "README.md",
        ]
    )
    if (classified["theorem_files"], classified["proof_files"], classified["definition_files"]) != (1, 2, 1):
        failures.append(f"Fermat path classes were {classified}")
    if classified["other_lean_files"] != ["FinalCheck.lean"] or classified["lean_files"] != 5:
        failures.append(f"Fermat other files were {classified}")
    extended = anthropic.classify_flt(
        [
            "Theorems/Thm_a.lean",
            "P2M/Sol/a.lean",
            "P2M/Util.lean",
            "Definitions/d.lean",
            "FinalCheck.lean",
            "lakefile.lean",
            "verification/comparator/Challenge.lean",
            "verification/comparator/Solution.lean",
            "README.md",
        ]
    )
    readme = (
        "All 5 modules of this repository built. "
        "(`Challenge.lean` uses `sorry` by design and is not part of the package)."
    )
    label = anthropic.module_count_label(5, extended, readme)
    expected_bits = (
        "README says 5 modules, which is the 4 files under Theorems, P2M, and Definitions plus FinalCheck.lean.",
        "The tree has 8 .lean files.",
        "The 3 extra .lean files are lakefile.lean, verification/comparator/Challenge.lean, and verification/comparator/Solution.lean.",
        "They are not package modules.",
        "The README says Challenge.lean is not part of the package.",
    )
    for bit in expected_bits:
        if bit not in label:
            failures.append(f"module-count label hid {bit!r}: {label}")
    if "(3 more)" in label or "Paths outside" in label:
        failures.append(f"module-count label still treats FinalCheck as an extra: {label}")
    if anthropic.module_count_label(5, extended, "All 5 modules of this repository built.").endswith(
        "not part of the package."
    ):
        failures.append("module-count label invented a Challenge.lean sentence the README does not say")
    page = (ROOT / "src" / "pages" / "source" / "anthropic.astro").read_text(encoding="utf-8")
    for status in ("NOT IN COMPARATOR", "NOT FORMALIZED", "NOTED"):
        if f'case "{status}":' not in page:
            failures.append(f"Anthropic source page badge does not handle {status}")
    if 'id={`gap-${gap.id}`}' not in page or 'id={`kind-${release.id}`}' not in page:
        failures.append("Anthropic source page does not key gap rows or kind badges")
    if "{gap.label}." in page:
        failures.append("Anthropic source page appends a period to every gap label")
    if "quotation.source" not in page or "quotation.text" not in page:
        failures.append("Anthropic source page does not label the source of each quotation")
    if "percolation" in page.lower():
        failures.append("Anthropic source page names percolation")
    social = (ROOT / "src" / "lib" / "social.ts").read_text(encoding="utf-8")
    if "source.preview.fragment" not in social or "source.org" not in social:
        failures.append("social alt text does not read each source preview")
    anthropic_preview = anthropic.anthropic_preview(
        {
            "source": {"name": "Anthropic", "org": "Anthropic"},
            "counts": {"lean_files": 61238, "releases": 3, "new_results": 2, "formalizations": 1},
        }
    )
    if "61238 Lean files from Anthropic (3 releases, 2 new results, 1 formalization)" not in anthropic_preview["fragment"]:
        failures.append(f"Anthropic preview fragment was {anthropic_preview['fragment']}")
    if atlaslib.FLT_PREVIEW_NOTE not in anthropic_preview["fragment"] or atlaslib.FLT_PREVIEW_NOTE not in anthropic_preview["detail"]:
        failures.append(f"Anthropic preview omitted the formalization note: {anthropic_preview}")
    if "\u2019" in anthropic_preview["fragment"] or "\u2019" in anthropic_preview["detail"]:
        failures.append("Anthropic preview uses a curly apostrophe")
    omitted = atlaslib.formalization_note_failures(
        "61238 Lean files from Anthropic (3 releases, 2 new results, 1 formalization)",
        "",
        "Math Release Atlas: 61238 Lean files from Anthropic.",
        "",
    )
    if not any("omits the formalization note" in item for item in omitted):
        failures.append("a preview without the formalization note was accepted")
    curly = atlaslib.FLT_PREVIEW_NOTE.replace("'", "\u2019")
    curly_note = atlaslib.formalization_note_failures(curly, curly, f"alt {curly}", curly)
    if not any("curly apostrophe" in item for item in curly_note):
        failures.append("a curly apostrophe in the formalization note was accepted")
    outside = (
        "<p>It is not the Riemann Hypothesis.</p>"
        '<section id="zeta23"><p>A lower bound on zeta zeros.</p></section>'
    )
    if not atlaslib.check_riemann_sentence(outside):
        failures.append("the Riemann Hypothesis sentence outside the zeta section was accepted")
    deleted = '<section id="zeta23"><p>It is the Riemann Hypothesis.</p></section>'
    if not atlaslib.check_riemann_sentence(deleted):
        failures.append("deleting the Riemann Hypothesis sentence was accepted")
    kept = f'<section id="zeta23"><p>{atlaslib.RIEMANN_SENTENCE}</p></section>'
    if atlaslib.check_riemann_sentence(kept):
        failures.append(f"the Riemann Hypothesis sentence was rejected: {atlaslib.check_riemann_sentence(kept)}")
    entries = [
        {
            "name": "OpenAI Math",
            "org": "OpenAI",
            "fragment": "372 result families and 719 manuscripts from the OpenAI Math catalogue",
            "tiles": [
                {"value": "372", "label": "result families"},
                {"value": "719", "label": "manuscripts"},
            ],
            "detail": "",
        },
        {
            "name": "AlphaProof Nexus",
            "org": "Google DeepMind",
            "fragment": "71 Lean files from AlphaProof Nexus, OEIS 38 of 44 in paper (PARTIAL), attempted list MATCH, per-row provenance MISSING",
            "tiles": [
                {"value": "71", "label": "Lean files"},
                {"value": "PARTIAL", "label": "OEIS 38 of 44"},
                {"value": "MATCH", "label": "attempted list"},
                {"value": "MISSING", "label": "provenance"},
            ],
            "detail": "Erdos 9, Stacks 11, AI collaborator 13",
        },
        {
            "name": "Anthropic",
            "org": "Anthropic",
            "fragment": anthropic_preview["fragment"],
            "tiles": anthropic_preview["tiles"],
            "detail": anthropic_preview["detail"],
        },
    ]
    alt = preview_alt(entries)
    if "not affiliated with OpenAI, Google DeepMind, or Anthropic." not in alt:
        failures.append(f"preview alt dropped an organization: {alt}")
    if scan_overclaims(alt, "preview"):
        failures.append("Anthropic preview alt was flagged")
    extra = {
        "name": "Example Source",
        "org": "Example Org",
        "fragment": "4 notes from Example Source",
        "tiles": [{"value": "4", "label": "notes"}],
        "detail": "",
    }
    try:
        image = og_card.render(entries)
        wider = og_card.render([*entries, extra])
    except SystemExit as exc:
        failures.append(f"preview card rejected a registered source: {exc}")
    else:
        if image.size != (atlaslib.PREVIEW_WIDTH, atlaslib.PREVIEW_HEIGHT):
            failures.append(f"Anthropic preview card is {image.size}")
        if wider.size != (atlaslib.PREVIEW_WIDTH, atlaslib.PREVIEW_HEIGHT):
            failures.append(f"a fourth source did not fit on the preview card: {wider.size}")
        drawn = og_card.planned_text([*entries, extra])
        if "Example Source" not in drawn or "Anthropic" not in drawn:
            failures.append(f"preview card omitted a source: {drawn}")
    return failures


def expect_error(label: str, func) -> str | None:
    try:
        func()
    except AtlasError:
        return None
    return f"self-test did not fail: {label}"


def self_test() -> list[str]:
    failures: list[str] = []
    sample = plainify(
        "Dirichlet <i>L</i>-function $`\\zeta(s)`$ in $`\\Re s\\gt 7/8`$, "
        "and SL<sub><i>n</i></sub>."
    )
    if sample != "Dirichlet L-function ζ(s) in Re s > 7/8, and SLₙ.":
        failures.append(f"plainify returned {sample!r}")
    title = plainify(r"$`\mathsf L=\mathsf{RL}=\mathsf{BPL}`$").rstrip(".")
    if title != "L=RL=BPL":
        failures.append(f"math title returned {title!r}")
    if parse_slug_date("Example-September-23-2026") != "2026-09-23":
        failures.append("month date parse failed")
    if parse_slug_date("Tangent-flow-uniqueness-2026-09-24") != "2026-09-24":
        failures.append("iso date parse failed")
    contents = """
**010. Parentheses.** A filling bound.

</td>
</tr>
<td>

&emsp;[Sharp integral fillings in CAT(0) spaces](preprints/Sharp-integral-fillings-in-CAT(0)-spaces-September-23-2026/paper.pdf)

Abstract with ABSTRACT-MARKER that must stay out of the summary.
"""
    parsed = parse_contents(contents)
    if len(parsed) != 1 or parsed[0]["manuscripts"][0]["slug"].endswith("2026") is False:
        failures.append("CAT(0) manuscript link was not parsed")
    slug = parsed[0]["manuscripts"][0]["slug"]
    if "CAT(0)" not in slug:
        failures.append(f"slug lost parentheses: {slug}")
    if "ABSTRACT-MARKER" in parsed[0]["upstream_summary"]:
        failures.append("summary included the manuscript abstract")
    for text in REQUIRED_CAUTIONS.values():
        if scan_overclaims(text, "caution"):
            failures.append(f"caution was flagged: {text}")
    for family_id in ("003", "376"):
        extended = REQUIRED_CAUTIONS[family_id].rstrip(".") + " and it is solved."
        if not scan_overclaims(extended, "caution"):
            failures.append(f"extended caution was not flagged: {extended}")
    # Phrases the sentence check rejected on main at 32c16fa2. Nothing here may pass.
    main_flagged = (
        "The Riemann Hypothesis is solved.",
        "The Riemann Hypothesis is not solved.",
        "This is not a proof of the Riemann Hypothesis.",
        "Never mind the skeptics; Navier-Stokes is cracked.",
        "RH proved.",
        "We resolved the Clay problem.",
        "The Millennium problem is settled.",
        "Navier–Stokes has been solved.",
        "proving the quasi-Riemann hypothesis.",
        "It is not a small result: the Riemann Hypothesis is solved.",
        "SOLVED the riemann hypothesis.",
        "Navier Stokes cracked.",
        "The Riemann\nHypothesis is solved.",
        "The Riemann Hypothesis is proven.",
        "There is a proof for the Riemann Hypothesis.",
        "We disprove Navier-Stokes.",
        "This disproves the Clay problem.",
        "The Millennium problem was disproved.",
        "RH is established.",
        "This establishes the Riemann Hypothesis.",
        "A solution to the Riemann Hypothesis.",
        "A solution of Navier-Stokes.",
        "R.H. is solved.",
        "The R.H. is proven.",
        "This is not a solution of the Riemann Hypothesis.",
        "Riemann's hypothesis is confirmed.",
        "Riemann's hypothesis is disproven.",
        "The Riemann Hypothesis was disproven.",
        "RH: proof complete.",
        "RH: proof complete",
        "We solved the Navier-Stokes equations.",
        "Navier-Stokes smoothness is proven.",
        "Global regularity of the Navier-Stokes equations is proven.",
        "Navier-Stokes blow-up is settled.",
        "The scheme proves a Navier-Stokes regularity estimate.",
        "RH is true.",
        "RH holds.",
        "The Riemann Hypothesis is now a theorem.",
        "We verify RH.",
        "RH follows.",
        "Our Navier–Stokes solver proves global regularity.",
        "We prove Navier–Stokes energy inequality implies global regularity.",
        "Navier–Stokes bounds settle the regularity question.",
        "The Riemann-Hypothesis is solved.",
        "Millennium-problem solved.",
        "We won the Clay prize.",
        "We show RH.",
        "We demonstrate the Riemann Hypothesis.",
        "RH is a theorem.",
        "RH is correct.",
        "RH has been shown.",
        "Navier–Stokes estimates prove blow up",
        "Navier–Stokes estimates prove blow–up",
        "We obtain RH",
        "We obtained the Riemann Hypothesis.",
        "We are obtaining RH.",
        "Riemann hypothesis: done",
        "Global smooth solutions of Navier-Stokes are proven.",
        "We solved Navier–Stokes flows.",
        "Navier–Stokes flows are solved.",
        "This settles Navier–Stokes flows.",
        "We prove Navier–Stokes flows exist globally.",
        "We crack Navier–Stokes flows.",
        "Navier–Stokes flows: proof complete.",
        "Navier–Stokes energy bounds for smooth data are proven and solve the problem.",
        "Navier–Stokes flows show turbulence",
        "We prove a Navier-Stokes energy inequality for smooth data.",
    )
    flagged = [
        *main_flagged,
        "A resolution of RH.",
        "Navier–Stokes: the proof.",
        "Navier–Stokes solution.",
        "We finish the Millennium problem.",
        "complete proof of RH",
        "RH: a complete proof.",
        "Navier–Stokes: a complete proof.",
        "A complete proof of the Millennium problem.",
        "A complete proof of the Clay problem.",
        "Navier–Stokes estimates: complete proof.",
        "Navier–Stokes solution: complete",
        "a full solution to RH",
        "the RH proof is complete",
        "RH proof.",
        "Proof: RH.",
        "Solution to RH.",
        "Solutions to RH.",
        "RH's proof.",
        "Our solution to RH.",
        "Complete solution of Navier–Stokes.",
        "Navier–Stokes solution is complete.",
        "Navier–Stokes global regularity: solution.",
        "A proof of the long-open conjecture known as the Riemann Hypothesis.",
        "A numerical proof of RH.",
        "Weak solution of the Riemann hypothesis.",
        "A disproof of RH.",
        "The lemma proof of RH.",
        "An approximate solution of the Clay problem.",
        "Strong solution of the Millennium problem.",
        "A solution to NavierStokes.",
        "RH disproof.",
        "RH disproofs.",
        "RH: proof scheme.",
        "proof of the R H",
        "A solution, long sought by many, to Navier–Stokes.",
        "NavierStokes solution",
        "A numerical proof of Navier–Stokes global regularity.",
        "Weak solutions of Navier–Stokes exist globally and are smooth.",
        "Weak solutions of Navier–Stokes: global regularity and smoothness.",
        "A numerical solution of Navier–Stokes gives a counterproof of blow-up.",
        "Numerical solution of the Navier–Stokes existence and smoothness problem.",
        "A weak solution of Navier–Stokes well-posedness.",
        "A numerical disproof of Navier–Stokes.",
        "Navier–Stokes numerical proof of the conjecture.",
        "Numerical solution of the Navier–Stokes problem.",
        "Numerical solution of Navier–Stokes is foolproof of the calculation.",
    ]
    review_ns = "Navier\u2013Stokes"
    review_flagged = [
        f"Weak solutions of {review_ns} are globally regular.",
        f"A weak solution of {review_ns} exists for all time.",
        f"Weak solutions of {review_ns} never develop singularities.",
        f"A weak solution of the {review_ns} question.",
        f"A Leray solution of {review_ns} exists globally.",
        f"Weak solutions of {review_ns} stay regular forever.",
        f"Weak solutions of {review_ns} have no singularities.",
        f"Weak solutions of {review_ns} are singularity-free.",
        f"Weak solutions of {review_ns} do not break down.",
        f"Weak solutions of {review_ns} are analytic for all time.",
        f"Weak solutions of {review_ns} persist for all time.",
        f"A weak solution of the {review_ns} challenge.",
        f"A weak solution of the {review_ns} prize.",
        f"A weak solution of the {review_ns} puzzle.",
        f"A weak solution of the {review_ns} riddle.",
        f"A weak solution of the {review_ns} open question.",
    ]
    review_flagged.extend(
        phrase.replace("\u2013", separator)
        for phrase in list(review_flagged)
        for separator in ("\u2011", "\u2014", "", "\uff0d")
    )
    flagged.extend(review_flagged)
    for text in main_flagged:
        if not scan_overclaims(text, "main"):
            failures.append(f"main phrase was not flagged: {text}")
    for text in flagged:
        if not scan_overclaims(text, "sample"):
            failures.append(f"overclaim was not flagged: {text}")
    allowed_sentence = "The Riemann Hypothesis is solved."
    if scan_overclaims(allowed_sentence, "sample", extra_allowed={allowed_sentence}):
        failures.append("exact allowlisted sentence was flagged")
    if not scan_overclaims(allowed_sentence.rstrip(".") + " today.", "sample", extra_allowed={allowed_sentence}):
        failures.append("near-copy of an allowlisted sentence was not flagged")
    allowed = [
        "This is not the Riemann Hypothesis.",
        "The Riemann Hypothesis remains open.",
        "The Riemann Hypothesis is unsolved.",
        "The Riemann Hypothesis is unproven.",
        "R.H. remains open.",
        "A linear system was solved.",
        "The lemma is proven.",
        "We prove a Navier-Stokes energy inequality.",
        "We prove a Navier–Stokes energy inequality.",
        "Navier–Stokes energy inequality.",
        "The scheme proves a Navier-Stokes approximation.",
        "Our Navier–Stokes solver proves an energy inequality.",
        "The lemma is a theorem.",
        "We show a bound.",
        "Navier–Stokes energy inequality for smooth data.",
        "Navier–Stokes energy inequality",
        "A complete proof of the lemma.",
        "A resolution of the linear system.",
        "A Navier–Stokes solution scheme",
        "numerical solution of Navier–Stokes",
        "The Navier–Stokes solution operator is bounded",
        "Weak solutions of Navier–Stokes",
        "Leray solutions of the Navier–Stokes equations",
        "A proof assistant checked the RH-type estimate.",
        "Proof of the lemma uses the Navier–Stokes energy inequality.",
        "mild solutions of Navier–Stokes",
        "strong solution of the Navier-Stokes equations",
        "approximate solution of Navier–Stokes",
    ]
    for text in allowed:
        if scan_overclaims(text, "sample"):
            failures.append(f"allowed sentence was flagged: {text}")
    if len(main_flagged) != 67:
        failures.append(f"main phrase list has {len(main_flagged)} entries")
    if len(allowed) != 28:
        failures.append(f"must-pass phrase list has {len(allowed)} entries")

    def why_overclaim(text: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "lenses": [
                            {
                                "tag": "plasma-kinetic",
                                "why": text,
                                "source": "A neutral source string for the regression.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    for text in flagged:
        message = expect_error(f"why overclaim {text}", lambda text=text: why_overclaim(text))
        if message:
            failures.append(message)
    hidden = "".join(chr(code) for code in (102, 117, 115, 105, 111, 110))
    device = "".join(chr(code) for code in (115, 117, 112, 101, 114, 99, 111, 110, 100, 117, 99, 116, 111, 114))
    generated = (
        hidden,
        hidden + "s",
        device,
        device + "s",
        device[:-2] + "ing",
        device + "2223",
        f"{device}-2223",
        f"tc-{device}-2223",
        device[:5] + "-" + device[5:],
    )
    for sample in generated:
        if not denylist_hit(sample):
            failures.append("denylist token was not flagged")
    if denylist_hit("advection-diffusion equation"):
        failures.append("a neighboring token matched the denylist")
    stem = "".join(chr(code) for code in (102, 117, 115, 105, 111, 110))
    after_many = "".join(chr(code) for code in (99, 97, 116, 101, 103, 111, 114, 105, 101, 115))
    after_one = "".join(chr(code) for code in (99, 97, 116, 101, 103, 111, 114, 121))
    before = "".join(chr(code) for code in (99, 111, 110, 110, 101, 115))
    warm = "".join(chr(code) for code in (114, 111, 111, 109))
    degree = "".join(
        chr(code)
        for code in (116, 101, 109, 112, 101, 114, 97, 116, 117, 114, 101)
    )
    short = "".join(chr(code) for code in (116, 101, 109, 112))
    compact = "".join(chr(code) for code in (108, 107))
    power = "".join(chr(code) for code in (112, 111, 119, 101, 114))
    allowed_phrases = (
        f"{stem} {after_many}",
        f"{stem} {after_one}",
        f"{before} {stem}",
        f"{stem}-{after_many}",
        f"{before}-{stem}",
        f"{stem}{after_many}",
    )
    for phrase in allowed_phrases:
        if denylist_hit(phrase):
            failures.append("a math compound containing the stem was flagged")
    denied_phrases = (
        f"{warm}-{degree}",
        f"{warm} {degree}",
        f"{warm}{degree}",
        f"{warm}-{short}",
        f"{warm} {short}",
        f"{warm}{short}",
        f"{compact}-99",
        f"{compact}99",
        f"{before} {stem} {power}",
        stem,
    )
    for phrase in denied_phrases:
        if not denylist_hit(phrase):
            failures.append("a denylist compound was not flagged")
    upstream_sentence = (
        "Proves that every Dirichlet L-function is zero-free in Re s > 7/8, "
        "resolving the quasi-Riemann hypothesis."
    )
    if not scan_overclaims(upstream_sentence, "upstream"):
        failures.append("an upstream-style claim sentence was not flagged")
    quoted = (
        f'<blockquote data-upstream="summary">{upstream_sentence}</blockquote>'
        "<p>The lemma is proven.</p>"
    )
    if not scan_overclaims(quoted, "page"):
        failures.append("an upstream quotation that is not a title was not flagged")
    # Rendered result of a template expression {"RH is " + "pro" + "ven."}.
    rendered_claim = '<p data-upstream="summary">RH is proven.</p>'
    if not scan_overclaims(rendered_claim, "template"):
        failures.append("a template-built claim inside an upstream element was not flagged")
    if not scan_overclaims(exempt_upstream_text(rendered_claim, {"The Riemann Hypothesis", "001"}), "template"):
        failures.append("a template-built claim was treated as an upstream title")
    exact_title = '<h1 data-upstream="title">RH is proven.</h1>'
    if scan_overclaims(exempt_upstream_text(exact_title, {"RH is proven.", "001"}), "template"):
        failures.append("an exact upstream title was flagged")
    exact_summary = (
        "Proves that every Dirichlet L-function is zero-free in Re s > 7/8, "
        "resolving the quasi-Riemann hypothesis."
    )
    summary_html = f'<blockquote data-upstream="summary">{exact_summary}</blockquote>'
    if scan_overclaims(exempt_upstream_text(summary_html, {exact_summary, "003"}), "template"):
        failures.append("an exact upstream summary was flagged")
    wrapped_img = (
        f'<blockquote data-upstream="summary"><img alt="RH is proven.">{exact_summary}</blockquote>'
    )
    exempted_img = exempt_upstream_text(wrapped_img, {exact_summary, "003"})
    if 'alt="RH is proven."' not in exempted_img or "Dirichlet" in exempted_img:
        failures.append("exemption blanked an image alt or left summary text")
    if not scan_overclaims(exempted_img, "template"):
        failures.append("an image alt inside an exempt summary was not flagged")
    wrapped_span = (
        '<blockquote data-upstream="summary">'
        f'<span title="RH is proven.">{exact_summary}</span></blockquote>'
    )
    exempted_span = exempt_upstream_text(wrapped_span, {exact_summary, "003"})
    if 'title="RH is proven."' not in exempted_span or "Dirichlet" in exempted_span:
        failures.append("exemption blanked a descendant title or left summary text")
    if not scan_overclaims(exempted_span, "template"):
        failures.append("a title attribute inside an exempt summary was not flagged")
    titled_summary = (
        f'<blockquote data-upstream="summary" title="RH is proven.">{exact_summary}</blockquote>'
    )
    exempted_title = exempt_upstream_text(titled_summary, {exact_summary, "003"})
    if 'title="RH is proven."' not in exempted_title or "Dirichlet" in exempted_title:
        failures.append("exemption blanked a title on the summary element or left summary text")
    if not scan_overclaims(exempted_title, "template"):
        failures.append("a title on an exempt summary element was not flagged")
    commented_summary = (
        f'<blockquote data-upstream="summary">{exact_summary}<!-- RH is proven. --></blockquote>'
    )
    exempted_comment = exempt_upstream_text(commented_summary, {exact_summary, "003"})
    if "<!-- RH is proven. -->" not in exempted_comment or "Dirichlet" in exempted_comment:
        failures.append("exemption dropped an HTML comment or left summary text")
    if not scan_overclaims(exempted_comment, "template"):
        failures.append("an HTML comment inside an exempt summary was not flagged")
    manuscript_title = "The Quasi-Riemann Hypothesis (alternate 11/12 proof)"
    manuscript_html = f'<a data-upstream="manuscript">{manuscript_title}</a>'
    if scan_overclaims(exempt_upstream_text(manuscript_html, {manuscript_title, "003"}), "template"):
        failures.append("an exact manuscript title was flagged")
    authored_claim = "<p>RH: proof complete.</p>"
    if not scan_overclaims(strip_upstream_quotes(authored_claim), "page"):
        failures.append("an authored claim in HTML was not flagged")
    marked = f'<h1 data-upstream="title">{stem}</h1><p>Hello.</p>'
    if not denylist_hit(marked):
        failures.append("a denylist token inside an upstream quotation was ignored")
    if not denylist_hit(strip_upstream_quotes(f"<p>{warm}-{degree}</p>")):
        failures.append("an authored denylist compound in HTML was not flagged")
    for attribute in (
        '<img alt="RH is solved">',
        '<a title="The Riemann Hypothesis is solved">x</a>',
        '<meta name="description" content="RH: proof complete">',
        '<span aria-label="We show RH">x</span>',
        "<input placeholder='RH is correct'>",
        "<img alt=RH-is-solved>",
        '<p aria-description="We obtain RH">x</p>',
        '<span data-note="Riemann hypothesis: done">x</span>',
    ):
        if not scan_overclaims(attribute, "attribute"):
            failures.append(f"a claim in an HTML attribute was not flagged: {attribute}")
    catalogue_attr = '<tr data-title="The Riemann Hypothesis is solved."><td>The lemma is proven.</td></tr>'
    if not scan_overclaims(catalogue_attr, "attribute"):
        failures.append("a claim in a data-title attribute was not flagged")
    graph_attr = '<svg data-title="The Riemann Hypothesis is proven."></svg>'
    if not scan_overclaims(graph_attr, "graph"):
        failures.append("a graph data-title claim was not flagged")
    exact_title = "The Riemann Hypothesis is proven."
    own_row = f'<tr id="f-001" data-title="{exact_title}"><td>The lemma is proven.</td></tr>'
    if scan_overclaims(exempt_index_rows(own_row, [{"id": "001", "title": exact_title}]), "row"):
        failures.append("an exact upstream title on its own row was flagged")
    forged_row = f'<tr id="f-002" data-title="{exact_title}"><td>The lemma is proven.</td></tr>'
    if not scan_overclaims(exempt_index_rows(forged_row, [{"id": "002", "title": "A different title"}]), "row"):
        failures.append("a forged data-title on another row was not flagged")
    sort_attr = '<th data-sort="title">Result</th>'
    if scan_overclaims(sort_attr, "attribute"):
        failures.append("a data-sort value was flagged")
    soft = chr(0x00AD)
    hidden_char = chr(0x200B)
    if not scan_overclaims(f"R{hidden_char}H is solved.", "normalized"):
        failures.append("a zero-width character hid a claim")
    if not scan_overclaims(f"Riem{soft}ann Hypothesis is solved.", "normalized"):
        failures.append("a soft hyphen hid a claim")
    fullwidth = f"{chr(0xFF32)}{chr(0xFF28)} is solved."
    if not scan_overclaims(fullwidth, "normalized"):
        failures.append("a compatibility character hid a claim")
    if not denylist_hit(stem[:3] + hidden_char + stem[3:]):
        failures.append("a zero-width character hid a denylist token")
    if not denylist_hit(stem[:3] + soft + stem[3:]):
        failures.append("a soft hyphen hid a denylist token")
    failures.extend(alphaproof_self_test())
    failures.extend(anthropic_self_test())
    failures.extend(ancestry_self_test())

    def missing_source() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "lenses": [{"tag": "plasma-kinetic", "why": "A kinetic model."}],
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    def solved_curated() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "003.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "003",
                        "lenses": [
                            {
                                "tag": "computation-hardness",
                                "why": "The Riemann Hypothesis is solved.",
                                "source": "no",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    def negated_curated() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "003.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "003",
                        "lenses": [
                            {
                                "tag": "computation-hardness",
                                "why": "This is not a proof of the Riemann Hypothesis.",
                                "source": "no",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    def bad_evidence_url() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "lenses": [
                            {
                                "tag": "plasma-kinetic",
                                "why": "A kinetic model.",
                                "source": "Upstream family summary for 362.",
                            }
                        ],
                        "community": {
                            "status": "claimed",
                            "evidence": [
                                {
                                    "url": "notes/local.md",
                                    "date": "2026-10-08",
                                    "note": "A short note.",
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    def ordinary_solved() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "lenses": [
                            {
                                "tag": "plasma-kinetic",
                                "why": "A linear system was solved.",
                                "source": "Upstream family summary for 362.",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    message = expect_error("missing source", missing_source)
    if message:
        failures.append(message)

    pinned = "a" * 40

    def catalogue_lens_missing_why() -> None:
        parse_catalogue_lens(
            {
                "tag": "number-theory",
                "why": " ",
                "source": f"https://example.com/{pinned}",
            },
            "catalogue lens",
            pinned,
        )

    def catalogue_lens_missing_source() -> None:
        parse_catalogue_lens(
            {
                "tag": "number-theory",
                "why": "The deposited file names a number.",
                "source": " ",
            },
            "catalogue lens",
            pinned,
        )

    def catalogue_lens_unpinned_source() -> None:
        parse_catalogue_lens(
            {
                "tag": "number-theory",
                "why": "The deposited file names a number.",
                "source": "https://example.com/file",
            },
            "catalogue lens",
            pinned,
        )

    for label, func in (
        ("catalogue lens missing why", catalogue_lens_missing_why),
        ("catalogue lens missing source", catalogue_lens_missing_source),
        ("catalogue lens unpinned source", catalogue_lens_unpinned_source),
    ):
        message = expect_error(label, func)
        if message:
            failures.append(message)

    record_url = f"https://example.com/{pinned}/file.lean"

    def catalogue_lens_record_url_mismatch() -> None:
        parse_catalogue_lens(
            {
                "tag": "algebraic-geometry",
                "why": "The deposited file states a prime spectrum.",
                "source": f"https://example.com/{pinned}/other.lean",
            },
            "catalogue lens",
            pinned,
            record_url=record_url,
        )

    message = expect_error("catalogue lens record url", catalogue_lens_record_url_mismatch)
    if message:
        failures.append(message)
    try:
        matched = parse_catalogue_lens(
            {
                "tag": "algebraic-geometry",
                "why": "The deposited file states a prime spectrum.",
                "source": record_url,
            },
            "catalogue lens",
            pinned,
            record_url=record_url,
        )
    except AtlasError as exc:
        failures.append(f"catalogue lens record url match rejected: {exc}")
        matched = None
    if matched is not None and matched["source"] != record_url:
        failures.append("catalogue lens record url match changed the source")

    own = "a" * 40
    foreign = "b" * 40
    pinned_href = f"https://github.com/openai/math/blob/{own}/overview.tex#L12"
    if _href_is_pinned(pinned_href, foreign):
        failures.append("a foreign commit counts as a pin")
    if not _href_is_pinned(pinned_href, own):
        failures.append("the source commit does not count as a pin")
    if _href_is_pinned("https://arxiv.org/abs/2608.13637", own):
        failures.append("an unversioned arXiv link counts as pinned")
    if not _href_is_pinned("https://arxiv.org/abs/2608.13637v1", own):
        failures.append("an arXiv v1 link does not count as pinned")
    if _href_is_pinned("Upstream family 090 summary", own):
        failures.append("prose counts as a pinned link")
    message = expect_error("curated solved", solved_curated)
    if message:
        failures.append(message)
    message = expect_error("curated negated proof", negated_curated)
    if message:
        failures.append(message)
    def status_without_evidence() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "community": {"status": "independently-checked", "evidence": []},
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    def status_with_evidence() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "community": {
                            "status": "disputed",
                            "evidence": [
                                {
                                    "url": "https://example.com/note",
                                    "date": "2026-10-08",
                                    "note": "A short neutral note about the family.",
                                }
                            ],
                            "history": [
                                {
                                    "status": "community-checking",
                                    "date": "2026-10-01",
                                    "note": "An earlier short note.",
                                    "url": "https://example.com/earlier",
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    def history_without_url() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "community": {
                            "status": "claimed",
                            "history": [
                                {
                                    "status": "retracted",
                                    "date": "2026-10-08",
                                    "note": "A short neutral note.",
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    message = expect_error("evidence url", bad_evidence_url)
    if message:
        failures.append(message)
    message = expect_error("status without evidence", status_without_evidence)
    if message:
        failures.append(message)
    def hostile_note() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "community": {
                            "status": "claimed",
                            "evidence": [
                                {
                                    "url": "https://example.com/note",
                                    "date": "2026-10-08",
                                    "note": "This paper is garbage and the authors are frauds.",
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    def quoted_evidence_url() -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "community": {
                            "status": "claimed",
                            "evidence": [
                                {
                                    "url": 'https://example.com/a"b',
                                    "date": "2026-10-08",
                                    "note": "A short note.",
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    message = expect_error("history without url", history_without_url)
    if message:
        failures.append(message)
    def curated_note(note: str) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "362.yaml"
            path.write_text(
                yaml.safe_dump(
                    {
                        "id": "362",
                        "community": {
                            "status": "claimed",
                            "evidence": [
                                {
                                    "url": "https://example.com/note",
                                    "date": "2026-10-08",
                                    "note": note,
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )
            validate_curated_file(path, yaml.safe_load(path.read_text(encoding="utf-8")))

    hostile_notes = (
        "The authors are liars.",
        "The argument is bogus.",
        "This is a crackpot note.",
        "The text was plagiarized.",
        "The note alleges plagiarism.",
        "The draft is junk.",
        "The speaker is a quack.",
        "The speaker is a charlatan.",
        "The authors cheat.",
        "The authors cheated.",
        "The note is dishonest.",
        "The claim is a sham.",
        "The note calls it junk-science.",
        "The note calls it sham-proof.",
        "The note calls it garbage-tier.",
        "The note calls it crack-pot.",
        "The note says crack pot.",
        "The author is a fraudster.",
        "The argument is fraudulent.",
        "The note shows dishonesty.",
        "The author is plagiarizing.",
        "The draft is junky.",
    )
    for sample in hostile_notes:
        message = expect_error(f"hostile note {sample}", lambda sample=sample: curated_note(sample))
        if message:
            failures.append(message)
    for sample in (
        "garbage collection",
        "fraud-detection",
        "fake-free",
        "scheme",
        "shampoo",
        "junction",
        "cheatsheet",
        "quackery",
        "cheat-sheet",
        "plagiarism-check",
        "junkers",
        "fraud detection",
        "sham pooled",
    ):
        try:
            curated_note(f"The method uses {sample}.")
        except AtlasError as exc:
            failures.append(f"a technical compound was rejected: {sample}: {exc}")
    message = expect_error("hostile note", hostile_note)
    if message:
        failures.append(message)
    message = expect_error("quoted evidence url", quoted_evidence_url)
    if message:
        failures.append(message)
    approval_error = approval_self_test()
    if approval_error:
        failures.append(approval_error)
    try:
        ordinary_solved()
        status_with_evidence()
    except AtlasError as exc:
        failures.append(f"a valid curated note was rejected: {exc}")
    cite_error = citation_self_test()
    if cite_error:
        failures.append(cite_error)
    merge_error = merge_status_self_test()
    if merge_error:
        failures.append(merge_error)
    if not CURATED_DIR.is_dir():
        failures.append("curated directory is missing")
    failures.extend(preview_self_test())
    failures.extend(spacing_self_test())
    return failures


def spacing_self_test() -> list[str]:
    """A run-together snapshot intro fails. The spaced sentence passes."""
    failures: list[str] = []
    phrase = (
        "Formalization scope: Partial progress. Generated 2026-10-09 from fd4aeeb2ee4f. "
        "Overview PDF · Manuscript map · Citation graph"
    )
    bad = (
        '<p class="provenance">Formalization scope: Partial progress.Generated 2026-10-09 from'
        '<a href="https://example.test/commit"><code>fd4aeeb2ee4f</code></a>.'
        '<a href="https://example.test/overview">Overview PDF</a>·'
        '<a href="https://example.test/contents">Manuscript map</a>·'
        '<a href="https://example.test/graph">Citation graph</a></p>'
    )
    good = (
        '<p class="provenance">Formalization scope: Partial progress. Generated 2026-10-09 from '
        '<a href="https://example.test/commit"><code>fd4aeeb2ee4f</code></a>. '
        '<a href="https://example.test/overview">Overview PDF</a> · '
        '<a href="https://example.test/contents">Manuscript map</a> · '
        '<a href="https://example.test/graph">Citation graph</a></p>'
    )
    if not atlaslib.missing_spaced_phrases(bad, [phrase]):
        failures.append("run-together snapshot intro was accepted")
    if atlaslib.missing_spaced_phrases(good, [phrase]):
        failures.append("spaced snapshot intro was rejected")
    glued_links = (
        "<p><a>AlphaProof Nexus counts and scope notes</a>·"
        "<a>Anthropic releases</a>·<a>Cross-source problem ids</a></p>"
    )
    spaced_links = (
        "<p><a>AlphaProof Nexus counts and scope notes</a> · "
        "<a>Anthropic releases</a> · <a>Cross-source problem ids</a></p>"
    )
    link_phrase = "AlphaProof Nexus counts and scope notes · Anthropic releases · Cross-source problem ids"
    if not atlaslib.missing_spaced_phrases(glued_links, [link_phrase]):
        failures.append("run-together source links were accepted")
    if atlaslib.missing_spaced_phrases(spaced_links, [link_phrase]):
        failures.append("spaced source links were rejected")
    return failures


def preview_self_test() -> list[str]:
    """A built page fails without og:image, without twitter:card, or with a relative image."""
    failures: list[str] = []
    if published_prefix() != "https://jkbennitt.github.io/math-release-atlas/":
        failures.append(f"published prefix is {published_prefix()!r}")
    prefix = "https://jkbennitt.github.io/math-release-atlas/"
    image = f"{prefix}og.png"
    title = "Math Release Atlas"
    description = "Unofficial table of result families."
    openai_only = [
        {
            "name": "OpenAI Math",
            "org": "OpenAI",
            "fragment": "372 result families and 722 manuscripts from the OpenAI Math catalogue",
        }
    ]
    alt = preview_alt(openai_only)
    if scan_overclaims(alt, "preview"):
        failures.append("preview alt was flagged")
    good = f"""
    <title>{title}</title>
    <meta name="description" content="{description}" />
    <link rel="canonical" href="{prefix}" />
    <meta property="og:title" content="{title}" />
    <meta property="og:description" content="{description}" />
    <meta property="og:url" content="{prefix}" />
    <meta property="og:type" content="website" />
    <meta property="og:site_name" content="Math Release Atlas" />
    <meta property="og:image" content="{image}" />
    <meta property="og:image:width" content="1200" />
    <meta property="og:image:height" content="630" />
    <meta property="og:image:alt" content="{alt}" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{title}" />
    <meta name="twitter:description" content="{description}" />
    <meta name="twitter:image" content="{image}" />
    <meta name="twitter:image:alt" content="{alt}" />
    """
    if check_social_preview(good, "fixture", prefix, openai_only):
        failures.append("a complete preview head was rejected")
    missing_image = good.replace(f'<meta property="og:image" content="{image}" />', "")
    if not any("missing og:image" in item for item in check_social_preview(missing_image, "fixture", prefix, openai_only)):
        failures.append("a page missing og:image was accepted")
    relative = good.replace(image, "/math-release-atlas/og.png")
    if not any("og:image is not absolute" in item for item in check_social_preview(relative, "fixture", prefix, openai_only)):
        failures.append("a relative og:image was accepted")
    missing_card = good.replace('<meta name="twitter:card" content="summary_large_image" />', "")
    if not any("missing twitter:card" in item for item in check_social_preview(missing_card, "fixture", prefix, openai_only)):
        failures.append("a page missing twitter:card was accepted")
    header = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 1200, 630)
    if png_dimensions(header + b"\x08\x02\x00\x00\x00") != (1200, 630):
        failures.append("png header parse failed")
    if png_dimensions(b"not a png") is not None:
        failures.append("a non-png had dimensions")
    rich_entries = [
        {
            "name": "OpenAI Math",
            "org": "OpenAI",
            "fragment": "372 result families and 719 manuscripts from the OpenAI Math catalogue",
        },
        {
            "name": "AlphaProof Nexus",
            "org": "Google DeepMind",
            "fragment": "71 Lean files from AlphaProof Nexus, OEIS 38 of 44 in paper (PARTIAL), attempted list MATCH, per-row provenance MISSING",
        },
    ]
    rich_alt = preview_alt(rich_entries)
    if "OEIS 38 of 44 in paper (PARTIAL)" not in rich_alt or "MATCH" not in rich_alt or "MISSING" not in rich_alt:
        failures.append("preview alt dropped an AlphaProof status")
    rich_page = good.replace(alt, rich_alt)
    if check_social_preview(rich_page, "fixture", prefix, rich_entries):
        failures.append("preview alt with the OEIS paper status was rejected")
    if not any("og:image:alt" in item for item in check_social_preview(good, "fixture", prefix, rich_entries)):
        failures.append("a preview alt without the OEIS paper status was accepted")
    anthropic_entries = [
        *rich_entries,
        {
            "name": "Anthropic",
            "org": "Anthropic",
            "fragment": "61238 Lean files from Anthropic (3 releases, 2 new results, 1 formalization)",
        },
    ]
    anthropic_alt = preview_alt(anthropic_entries)
    if "61238 Lean files from Anthropic (3 releases, 2 new results, 1 formalization)" not in anthropic_alt:
        failures.append("preview alt dropped the Anthropic counts")
    if not anthropic_alt.endswith("Unofficial, not affiliated with OpenAI, Google DeepMind, or Anthropic."):
        failures.append("preview alt dropped the Anthropic affiliation")
    if scan_overclaims(anthropic_alt, "preview"):
        failures.append("Anthropic preview alt was flagged")
    anthropic_page = good.replace(alt, anthropic_alt)
    if check_social_preview(anthropic_page, "fixture", prefix, anthropic_entries):
        failures.append("preview alt with the Anthropic counts was rejected")
    if not any("og:image:alt" in item for item in check_social_preview(rich_page, "fixture", prefix, anthropic_entries)):
        failures.append("a preview alt without the Anthropic counts was accepted")
    if "Anthropic" in preview_alt(openai_only):
        failures.append("preview alt named Anthropic without a registered source")
    catalog = read_json(FAMILIES_JSON)
    entries = atlaslib.preview_entries(catalog["sources"]["sources"])
    image = og_card.render(entries)
    blob = og_card.png_bytes(image)
    if og_card.png_bytes(og_card.render(entries)) != blob:
        failures.append("preview card png is not deterministic")
    with tempfile.TemporaryDirectory() as tmp:
        dist = Path(tmp)
        (dist / "og.png").write_bytes(blob)
        matched = atlaslib.check_preview_image(dist, catalog)
        if matched:
            failures.append(f"the rendered card was rejected: {matched}")
        blank = Image.new("RGB", (atlaslib.PREVIEW_WIDTH, atlaslib.PREVIEW_HEIGHT), (255, 255, 255))
        (dist / "og.png").write_bytes(og_card.png_bytes(blank))
        blank_failures = atlaslib.check_preview_image(dist, catalog)
        if not any("does not match" in item for item in blank_failures):
            failures.append(f"a blank og.png was accepted: {blank_failures}")
        stale = image.copy()
        stale.putpixel((8, 8), (1, 2, 3))
        (dist / "og.png").write_bytes(og_card.png_bytes(stale))
        if not atlaslib.check_preview_image(dist, catalog):
            failures.append("a stale og.png was accepted")
    unchecked = copy.deepcopy(catalog)
    unchecked["sources"]["sources"].append(
        {
            "id": "unchecked",
            "name": "Unchecked",
            "org": "Unchecked Org",
            "preview": {
                "fragment": "99999 notes from Unchecked",
                "tiles": [{"value": "99999", "label": "notes"}],
                "detail": "",
                "bindings": [{"value": "99999", "path": ["unchecked", "notes"]}],
            },
        }
    )
    unchecked["unchecked"] = {"notes": 99999}
    unchecked_failures = atlaslib.preview_disagreements(unchecked)
    if not any("no preview derivation" in item for item in unchecked_failures):
        failures.append(f"a source counted as 99999 with no derivation was accepted: {unchecked_failures}")
    renamed = copy.deepcopy(catalog)
    for source in renamed["sources"]["sources"]:
        if source["id"] == "openai-math":
            source["org"] = "OpenAI Inc"
    renamed_failures = atlaslib.preview_disagreements(renamed)
    if not any("expected 'OpenAI'" in item for item in renamed_failures):
        failures.append(f"renaming OpenAI in the affiliation line was accepted: {renamed_failures}")
    return failures


def citation_self_test() -> str | None:
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        alpha = repo / "preprints" / "alpha-paper" / "build"
        beta = repo / "preprints" / "beta-paper" / "build"
        alpha.mkdir(parents=True)
        beta.mkdir(parents=True)
        (alpha / "b.tex").write_text("See OAI:beta-paper and OAI:alpha-paper.\n", encoding="utf-8")
        (alpha / "a.bib").write_text("OAI:beta-paper\n", encoding="utf-8")
        families = [
            {"id": "001", "manuscripts": [{"slug": "alpha-paper"}]},
            {"id": "002", "manuscripts": [{"slug": "beta-paper"}]},
        ]
        attach_citations(repo, "a" * 40, families)
        edges = families[0]["citations"]
        if len(edges) != 1 or edges[0]["to"] != "002":
            return f"citation edge was {edges}"
        if edges[0]["source"] != "preprints/alpha-paper/build/a.bib":
            return f"citation receipt was {edges[0]['source']}"
        if not edges[0]["url"].endswith("/preprints/alpha-paper/build/a.bib"):
            return f"citation url was {edges[0]['url']}"
        if families[1]["citations"] != []:
            return "a self-citation or reverse edge was kept"
    return None


def approval_self_test() -> str | None:
    note = "A short neutral note about the family."
    day = "2026-10-08"
    evidence = {"url": "https://example.com/note", "date": day, "note": note}
    community = {"status": "disputed", "evidence": [evidence], "history": []}
    curated = {"362": {"id": "362", "community": community}}
    if not approval_mismatches(curated, []):
        return "a disputed status without an allowlist entry was accepted"
    entry = {
        "id": "362",
        "status": "disputed",
        "url": "https://example.com/note",
        "date": day,
        "note": note,
        "approver": "jkbennitt",
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "status-approvals.yaml"
        path.write_text(yaml.safe_dump({"approvals": [entry]}), encoding="utf-8")
        approvals = load_status_approvals(path)
    mismatches = approval_mismatches(curated, approvals)
    if mismatches:
        return f"a matching status approval was rejected: {mismatches[0]}"
    edited_note = {
        "362": {
            "id": "362",
            "community": {
                "status": "disputed",
                "evidence": [{**evidence, "note": "A short neutral note about the family, revised."}],
                "history": [],
            },
        }
    }
    if not approval_mismatches(edited_note, approvals):
        return "an edited note still matched the allowlist"
    edited_date = {
        "362": {
            "id": "362",
            "community": {
                "status": "disputed",
                "evidence": [{**evidence, "date": "2026-10-09"}],
                "history": [],
            },
        }
    }
    if not approval_mismatches(edited_date, approvals):
        return "an edited date still matched the allowlist"
    return None


def merge_status_self_test() -> str | None:
    evidence = {
        "url": "https://example.com/note",
        "date": "2026-10-08",
        "note": "A short neutral note about the family.",
    }
    community = {"status": "independently-checked", "evidence": [evidence], "history": []}
    upstream = {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "upstream": {},
        "counts": {},
        "areas": [],
        "families": [
            {
                "id": "001",
                "citations": [
                    {
                        "to": "002",
                        "via": "OAI:beta-paper",
                        "source": "preprints/alpha-paper/build/a.bib",
                        "url": "https://example.com/a.bib",
                    }
                ],
            },
            {"id": "002"},
        ],
    }
    curated = {
        "001": {
            "id": "001",
            "lenses": [],
            "related": [{"to": "002", "kind": "shared-topic", "why": "Same topic.", "source": "Hand grouping"}],
            "community": community,
            "caution": None,
        }
    }
    merged = merge_data(upstream, curated, {})
    first, second = merged["families"]
    if first["community"] != community:
        return "merge did not keep the curated community status"
    if second["community"] is not None:
        return "merge invented a community status"
    if "citations" in first or first["cites"][0]["to"] != "002":
        return "merge did not project cites"
    if second["cited_by"][0]["from"] != "001" or second["cited_by"][0]["url"] != "https://example.com/a.bib":
        return "merge did not project cited_by"
    if first["cited_by"] != [] or second["cites"] != []:
        return "merge added an extra citation edge"
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="store_true", help="Check generated data and authored text.")
    parser.add_argument("--dist", type=Path, help="Check built HTML.")
    parser.add_argument("--self-test", action="store_true", help="Run guard fixtures.")
    parser.add_argument(
        "--verify-upstream",
        action="store_true",
        help="Sparse-fetch the commit named in upstream.json and fail if the snapshot differs.",
    )
    args = parser.parse_args()
    if not (args.source or args.dist or args.self_test or args.verify_upstream):
        args.source = True
        args.self_test = True
    failures: list[str] = []
    if args.self_test:
        failures.extend(self_test())
    if args.source:
        failures.extend(check_source())
    if args.verify_upstream:
        try:
            verify_recorded_upstream()
            verify_recorded_alphaproof()
            verify_recorded_anthropic()
        except AtlasError as exc:
            failures.append(str(exc))
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "").strip().splitlines()
            failures.append(detail[-1] if detail else "could not fetch upstream")
    if args.dist:
        failures.extend(check_dist(args.dist))
    if failures:
        for failure in failures:
            print(f"error: {failure}", file=sys.stderr)
        return 1
    print("checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
