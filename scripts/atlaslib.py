"""Parse the upstream catalogue, merge hand-written notes, and check claims."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import subprocess
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import yaml

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM_JSON = ROOT / "data" / "upstream.json"
FAMILIES_JSON = ROOT / "data" / "families.json"
CURATED_DIR = ROOT / "data" / "curated"
CAUTIONS_JSON = ROOT / "data" / "fixed-cautions.json"
UPSTREAM_URL = "https://github.com/openai/math.git"
UPSTREAM_WEB = "https://github.com/openai/math"

LENS_TAGS = {
    "condensed-matter",
    "plasma-kinetic",
    "fluids-continuum",
    "electronic-structure",
    "quantum-information",
    "gravity-qft",
    "computation-hardness",
}
COMMUNITY_STATUSES = {
    "claimed",
    "community-confirmed",
    "disputed",
    "broken",
}
STATUSES_NEEDING_EVIDENCE = {
    "community-confirmed",
    "disputed",
    "broken",
}
LEAN_STATUSES = (
    "main-result-formalized",
    "comparator-challenge-only",
    "none",
)
CURATED_KEYS = {"id", "lenses", "related", "community", "caution"}
SPARSE_PATHS = [
    "/CONTENTS.md",
    "/overview.tex",
    "/README.md",
    "/lean/formalization.yaml",
    "/lean/docs/",
]

# Counts checked against openai/math @ adc7f1241b42 (Initial commit).
PINNED_COMMIT = "adc7f1241b42e322a6451854ab7e4b4c146bf78a"
PINNED_COUNTS = {
    "families": 372,
    "manuscripts": 722,
    "main_result_formalized": 127,
    "comparator_challenge_only": 108,
    "none": 137,
    "yaml_sources": 162,
    "lean_docs": 235,
    "comparator_files": 405,
    "reasoning_traces": 10,
    "areas": 17,
}
PINNED_MISSING_IDS = ["045", "061", "070", "123", "163"]
PINNED_AREAS = [
    ("Number theory", 31),
    ("Algebraic and complex geometry", 36),
    ("Real and complex analysis", 16),
    ("Convex and metric geometry", 15),
    ("Theoretical computer science", 40),
    ("Dynamical systems and ergodic theory", 12),
    ("Combinatorics", 37),
    ("Algebra", 18),
    ("Probability and statistical mechanics", 29),
    ("Mathematical logic", 6),
    ("Group theory", 14),
    ("Mathematical physics", 25),
    ("Operator algebras", 19),
    ("Topology", 18),
    ("Functional analysis", 11),
    ("Differential geometry", 29),
    ("Partial differential equations", 16),
]

# A sentence is an overclaim when it names one of these problems and uses a claim verb.
# RH and dotted R.H.; Riemann Hypothesis; Navier-Stokes (hyphen, dash, or space); Clay; Millennium.
CLAIM_TOPIC_RE = re.compile(
    r"\brh\b|r\s*\.\s*h\s*\.|riemann\s+hypothesis|"
    r"navier[\s\-\u2010\u2011\u2012\u2013\u2014\u2212]*stokes|\bclay\b|\bmillennium\b",
    re.IGNORECASE,
)
# prove/proves/proved/proving/proven, disprove/disproves/disproved/disproving,
# proof of/for, establish/establishes/established/establishing, a solution to, solution of,
# resolve/resolves/resolved/resolving, settle/settles/settled/settling,
# solve/solves/solved/solving, crack/cracks/cracked/cracking.
CLAIM_VERB_RE = re.compile(
    r"\bproven\b|\bprov(?:e|es|ed|ing)\b|\bdisprov(?:e|es|ed|ing)\b|"
    r"proofs?\s+(?:of|for)|\bestablish(?:es|ed|ing)?\b|"
    r"\bsolutions?\s+(?:to|of)\b|"
    r"\bresolv(?:e|es|ed|ing)\b|\bsettl(?:e|es|ed|ing)\b|"
    r"\bsolv(?:e|es|ed|ing)\b|\bcrack(?:s|ed|ing)?\b",
    re.IGNORECASE,
)
# SHA-256 of lowercase denylist stems. The stems are not stored in this repository.
DENYLIST_DIGESTS = frozenset(
    {
        "f5d36c673cea1d80af3d33404d506e0c3e7aeaa0b8c1a21e085fa3caa8928b3b",
        "5edc19b4eb5c54ecfb92717b75df2d0717c13803a757d86d82408a2b7de95ada",
        "703d12e6c22e5217af3eb55d340a77ef66cb448d1a4d43c29de38c80df0ac718",
        "2172bcaf476e331c9c9f28b0d23051c43af1cef2f2e6c606265c2df9c52d0579",
        "71a1857de590aa60b6bd09083cf964ef33e21e09bd54b4c1352e414535b6021b",
        "f0ccbd04b51bbc1232b2c3b8bd95110319b199d3097e60a7abd91ec1b12ef65f",
    }
)
DENYLIST_MIN_PREFIX = 6
DENYLIST_SUFFIXES = ("ivity", "ing", "ers", "ion", "ors", "ive", "es", "ed", "ly", "al", "s")
TOKEN_RE = re.compile(r"[a-z0-9]+")
HYPHEN_RUN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")
DENYLIST_SKIP = {".git", "node_modules", "dist", ".astro", "__pycache__"}

MONTHS = {
    "January": 1,
    "February": 2,
    "March": 3,
    "April": 4,
    "May": 5,
    "June": 6,
    "July": 7,
    "August": 8,
    "September": 9,
    "October": 10,
    "November": 11,
    "December": 12,
}
BLACKBOARD = {
    "C": "ℂ",
    "F": "𝔽",
    "H": "ℍ",
    "N": "ℕ",
    "Q": "ℚ",
    "R": "ℝ",
    "Z": "ℤ",
}
GREEK = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "epsilon": "ε",
    "varepsilon": "ε",
    "varphi": "φ",
    "zeta": "ζ",
    "eta": "η",
    "theta": "θ",
    "kappa": "κ",
    "lambda": "λ",
    "mu": "μ",
    "nu": "ν",
    "xi": "ξ",
    "pi": "π",
    "rho": "ρ",
    "sigma": "σ",
    "tau": "τ",
    "phi": "φ",
    "psi": "ψ",
    "omega": "ω",
    "ell": "ℓ",
    "infty": "∞",
}
DROP_COMMANDS = {
    "left",
    "right",
    "nolimits",
    "limits",
    "displaystyle",
    "textstyle",
    "bigl",
    "bigr",
    "Bigl",
    "Bigr",
    "quad",
    "qquad",
    "!",
    ",",
    ";",
    ":",
    " ",
}
SUP_MAP = str.maketrans("0123456789+-=()ni", "⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻⁼⁽⁾ⁿⁱ")
SUB_MAP = str.maketrans("0123456789+-=()n", "₀₁₂₃₄₅₆₇₈₉₊₋₌₍₎ₙ")
FAMILY_RE = re.compile(r"\*\*(?P<id>\d{3})\.\s(?P<title>.*?)\*\*", re.S)
MANUSCRIPT_RE = re.compile(
    r"&emsp;\[([^\]]+)\]\((preprints/(?:[^()\n]|\([^()\n]*\))+)\)"
)
MONTH_DATE_RE = re.compile(
    r"-(January|February|March|April|May|June|July|August|September|"
    r"October|November|December)-(\d{1,2})-(\d{4})$"
)
ISO_DATE_RE = re.compile(r"-(\d{4})-(\d{2})-(\d{2})$")


class AtlasError(Exception):
    """The catalogue could not be parsed or a check failed."""


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8")


def unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    )
    return result.stdout


def blob_url(commit: str, path: str) -> str:
    encoded = quote(path, safe="/")
    return f"{UPSTREAM_WEB}/blob/{commit}/{encoded}"


def parse_slug_date(slug: str) -> str:
    iso = ISO_DATE_RE.search(slug)
    if iso:
        year, month, day = (int(part) for part in iso.groups())
        return date(year, month, day).isoformat()
    named = MONTH_DATE_RE.search(slug)
    if named:
        month_name, day_s, year_s = named.groups()
        return date(int(year_s), MONTHS[month_name], int(day_s)).isoformat()
    raise AtlasError(f"manuscript folder has no date: {slug}")


def math_pass(text: str) -> str:
    text = re.sub(r"\\overline\s*\{([^{}]*)\}", r"\1", text)
    def blackboard_word(match: re.Match[str]) -> str:
        return "".join(BLACKBOARD.get(char, char) for char in match.group(1))

    text = re.sub(r"\\mathbb\s*\{([A-Za-z]+)\}", blackboard_word, text)
    text = re.sub(r"\\mathbb\s+([A-Za-z]+)", blackboard_word, text)
    for command in ("mathcal", "mathsf", "mathrm", "mathbf", "operatorname", "text"):
        text = re.sub(rf"\\{command}\s*\{{([^{{}}]*)\}}", r"\1", text)
        text = re.sub(rf"\\{command}\s+([A-Za-z]+)", r"\1", text)
        text = re.sub(rf"\\{command}(?![A-Za-z])", "", text)
    text = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"√(\1)", text)
    text = re.sub(r"\\sqrt\s*([A-Za-z0-9])", r"√\1", text)
    replacements = {
        r"\Re": "Re",
        r"\gt": " > ",
        r"\lt": " < ",
        r"\geq": " ≥ ",
        r"\leq": " ≤ ",
        r"\ge": " ≥ ",
        r"\le": " ≤ ",
        r"\times": " × ",
        r"\cdot": " · ",
        r"\to": " → ",
        r"\log": "log",
        r"\sum": "Σ",
        r"\prod": "Π",
        r"\int": "∫",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    text = re.sub(r"\\[,;:! ]", "", text)

    def greek(match: re.Match[str]) -> str:
        name = match.group(1)
        if name in DROP_COMMANDS:
            return ""
        return GREEK.get(name, name)

    return re.sub(r"\\([A-Za-z]+)", greek, text)


def convert_math(src: str) -> str:
    text = src.replace(r"\{", "{").replace(r"\}", "}").replace(r"\|", "‖")
    for _ in range(6):
        updated = math_pass(text)
        if updated == text:
            break
        text = updated
    text = text.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", text).strip()


def apply_script(inner: str, mapping: dict[int, str]) -> str:
    cleaned = re.sub(r"</?i>", "", inner)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    return cleaned.translate(mapping)


def plainify(text: str) -> str:
    without_lean = re.sub(r"\(\[Lean\]\(lean/docs/\d+\.md\)\)", "", text)
    with_math = re.sub(r"\$`([^`]*)`\$", lambda match: convert_math(match.group(1)), without_lean)
    with_math = re.sub(
        r"\$(?!`)([^$]+?)\$",
        lambda match: convert_math(match.group(1)),
        with_math,
    )
    unescaped = html.unescape(with_math)
    unescaped = re.sub(
        r"<sup>(.*?)</sup>",
        lambda match: apply_script(match.group(1), SUP_MAP),
        unescaped,
        flags=re.S,
    )
    unescaped = re.sub(
        r"<sub>(.*?)</sub>",
        lambda match: apply_script(match.group(1), SUB_MAP),
        unescaped,
        flags=re.S,
    )
    unescaped = re.sub(r"</?i>", "", unescaped)
    unescaped = re.sub(r"<[^>]+>", " ", unescaped)
    unescaped = unescaped.replace("\u00a0", " ")
    return re.sub(r"\s+", " ", unescaped).strip()


def parse_contents(text: str) -> list[dict[str, Any]]:
    matches = list(FAMILY_RE.finditer(text))
    if not matches:
        raise AtlasError("CONTENTS.md has no family headings")
    families: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, match in enumerate(matches):
        family_id = match.group("id")
        if family_id in seen:
            raise AtlasError(f"duplicate family id {family_id}")
        seen.add(family_id)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end]
        title = plainify(match.group("title")).rstrip(".")
        if not title:
            raise AtlasError(f"family {family_id} has an empty title")
        cell = body.split("</td>", 1)[0]
        summary = plainify(cell)
        if not summary:
            raise AtlasError(f"family {family_id} has an empty summary")
        manuscripts = []
        slugs: set[str] = set()
        for link in MANUSCRIPT_RE.finditer(body):
            raw_title, rel = link.group(1), link.group(2)
            parts = rel.split("/")
            if len(parts) < 3 or parts[0] != "preprints":
                raise AtlasError(f"bad manuscript path in {family_id}: {rel}")
            slug = parts[1]
            if slug in slugs:
                raise AtlasError(f"duplicate manuscript {slug} in family {family_id}")
            slugs.add(slug)
            manuscripts.append(
                {
                    "slug": slug,
                    "title": plainify(raw_title),
                    "pdf_path": rel,
                    "date": parse_slug_date(slug),
                }
            )
        if not manuscripts:
            raise AtlasError(f"family {family_id} has no manuscripts")
        families.append(
            {
                "id": family_id,
                "title": title,
                "upstream_summary": summary,
                "manuscripts": manuscripts,
            }
        )
    return families


def parse_areas(tex: str) -> tuple[dict[str, list[str]], list[tuple[str, int]]]:
    current: str | None = None
    mapping: dict[str, list[str]] = {}
    order: list[str] = []
    counts: dict[str, int] = defaultdict(int)
    for line in tex.splitlines():
        section = re.search(r"\\cataloguesection\{(.+?)\}\{", line)
        if section:
            current = section.group(1)
            order.append(current)
            continue
        entry = re.search(r"\\resultentry\{(\d{3})\}", line)
        if entry:
            if current is None:
                raise AtlasError(f"result {entry.group(1)} appears before any subject")
            family_id = entry.group(1)
            mapping.setdefault(family_id, [])
            if current not in mapping[family_id]:
                mapping[family_id].append(current)
                counts[current] += 1
    area_counts = [(name, counts[name]) for name in order]
    return mapping, area_counts


def parse_formalization(text: str) -> dict[str, Any]:
    section = ""
    in_main = False
    sources: list[str] = []
    declarations: dict[str, list[str]] = defaultdict(list)
    current_config: str | None = None
    scope = ""
    review = ""
    main_rows = 0
    for line in text.splitlines():
        top = re.match(r"^([A-Za-z0-9_]+):", line)
        if top:
            section = top.group(1)
            in_main = False
            current_config = None
            continue
        if section == "sources":
            source = re.match(r"\s+id:\s+\.\./preprints/([^/\s]+)/(\S+)\s*$", line)
            if source:
                sources.append(source.group(1))
            continue
        if section == "status":
            if line.startswith("  scope:"):
                scope = unquote(line.split(":", 1)[1])
            if line.strip() == "main_results:":
                in_main = True
                continue
            if not in_main:
                continue
            config = re.match(r"\s+-\s+comparator_config:\s+(\S+)\s*$", line)
            if config:
                current_config = config.group(1)
                main_rows += 1
                continue
            declaration = re.match(r"\s+declaration:\s+(.+?)\s*$", line)
            if declaration and current_config:
                declarations[current_config].append(unquote(declaration.group(1)))
            continue
        if section == "review" and line.strip().startswith("status:"):
            review = unquote(line.split(":", 1)[1])
    if not sources:
        raise AtlasError("formalization.yaml has no preprint sources")
    if not scope or not review:
        raise AtlasError("formalization.yaml is missing scope or review status")
    return {
        "sources": sources,
        "declarations": declarations,
        "scope": scope,
        "review_status": review,
        "main_result_rows": main_rows,
    }


def parse_readme(text: str) -> dict[str, Any]:
    sentence = re.search(
        r"The current catalogue contains (\d+) manuscripts organized into (\d+) families\.",
        text,
    )
    if not sentence:
        raise AtlasError("upstream README is missing the catalogue count sentence")
    traces = []
    for family_id, subject, path in re.findall(
        r"^\| (\d{3}) \| \[([^\]]+)\]\((reasoning_traces/[^)]+)\) \|",
        text,
        flags=re.M,
    ):
        traces.append({"id": family_id, "subject": subject, "path": path})
    return {
        "manuscripts": int(sentence.group(1)),
        "families": int(sentence.group(2)),
        "sentence": sentence.group(0),
        "traces": traces,
    }


def parse_contents_headline(text: str) -> tuple[int, int]:
    headline = re.search(
        r"\*\*(\d+) manuscripts covering (\d+) result families\.\*\*",
        text,
    )
    if not headline:
        raise AtlasError("CONTENTS.md is missing the manuscript/family headline")
    return int(headline.group(1)), int(headline.group(2))


def list_tree(repo: Path, commit: str, path: str) -> list[str]:
    output = git(repo, "ls-tree", "-r", "--name-only", f"{commit}:{path}")
    return [line for line in output.splitlines() if line]


def list_dirs(repo: Path, commit: str, path: str) -> list[str]:
    output = git(repo, "ls-tree", "-d", "--name-only", f"{commit}:{path}")
    return [line for line in output.splitlines() if line]


def comparator_index(names: list[str]) -> dict[str, set[str]]:
    stems: dict[str, set[str]] = defaultdict(set)
    for name in names:
        if name.endswith(".lean") or name.endswith(".json"):
            stem, _, suffix = name.rpartition(".")
            stems[stem].add(suffix)
    return stems


def read_comparators(doc_text: str) -> list[str]:
    return sorted(set(re.findall(r"ComparatorChallenges/([A-Za-z0-9_.-]+)\.lean", doc_text)))


def build_upstream(repo: Path) -> tuple[dict[str, Any], bool]:
    commit = git(repo, "rev-parse", "HEAD").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise AtlasError(f"unexpected commit sha: {commit}")
    contents = (repo / "CONTENTS.md").read_text(encoding="utf-8")
    overview = (repo / "overview.tex").read_text(encoding="utf-8")
    readme = (repo / "README.md").read_text(encoding="utf-8")
    formalization_text = (repo / "lean" / "formalization.yaml").read_text(encoding="utf-8")

    families = parse_contents(contents)
    areas, area_counts = parse_areas(overview)
    formalization = parse_formalization(formalization_text)
    readme_meta = parse_readme(readme)
    headline_manuscripts, headline_families = parse_contents_headline(contents)
    preprint_dirs = set(list_dirs(repo, commit, "preprints"))
    doc_tree = [name for name in list_tree(repo, commit, "lean/docs") if name.endswith(".md")]
    doc_disk = sorted(path.name for path in (repo / "lean" / "docs").glob("*.md"))
    if sorted(doc_tree) != doc_disk:
        raise AtlasError(
            f"lean/docs checkout has {len(doc_disk)} files; the commit tree has {len(doc_tree)}"
        )
    comparator_files = list_tree(repo, commit, "lean/ComparatorChallenges")
    comparators = comparator_index(comparator_files)
    source_slugs = set(formalization["sources"])
    trace_by_id = {item["id"]: item for item in readme_meta["traces"]}

    if len(formalization["sources"]) != len(source_slugs):
        raise AtlasError("formalization.yaml lists the same manuscript twice")
    missing_sources = sorted(source_slugs - preprint_dirs)
    if missing_sources:
        raise AtlasError(f"formalization.yaml names unknown manuscripts: {missing_sources[:5]}")

    built: list[dict[str, Any]] = []
    for family in families:
        family_id = family["id"]
        if family_id not in areas:
            raise AtlasError(f"family {family_id} has no subject in overview.tex")
        manuscripts = []
        for item in family["manuscripts"]:
            if item["slug"] not in preprint_dirs:
                raise AtlasError(f"missing preprint directory {item['slug']}")
            manuscripts.append(
                {
                    "slug": item["slug"],
                    "title": item["title"],
                    "date": item["date"],
                    "pdf": blob_url(commit, item["pdf_path"]),
                    "main_result_formalized": item["slug"] in source_slugs,
                }
            )
        manuscripts.sort(key=lambda item: (item["date"], item["slug"]))
        doc_file = repo / "lean" / "docs" / f"{family_id}.md"
        comparator_rows: list[dict[str, Any]] = []
        doc_url = None
        if doc_file.is_file():
            doc_url = blob_url(commit, f"lean/docs/{family_id}.md")
            for stem in read_comparators(doc_file.read_text(encoding="utf-8")):
                suffixes = comparators.get(stem, set())
                if "lean" not in suffixes or "json" not in suffixes:
                    raise AtlasError(
                        f"family {family_id} links missing Comparator file {stem}"
                    )
                config = f"ComparatorChallenges/{stem}.json"
                comparator_rows.append(
                    {
                        "file": f"lean/ComparatorChallenges/{stem}.lean",
                        "url": blob_url(commit, f"lean/ComparatorChallenges/{stem}.lean"),
                        "declarations": formalization["declarations"].get(config, []),
                    }
                )
        formalized = any(item["main_result_formalized"] for item in manuscripts)
        if formalized:
            status = "main-result-formalized"
        elif doc_url and comparator_rows:
            status = "comparator-challenge-only"
        else:
            status = "none"
        trace = trace_by_id.get(family_id)
        reasoning = None
        if trace:
            reasoning = {
                "path": trace["path"],
                "subject": trace["subject"],
                "url": blob_url(commit, trace["path"]),
            }
        built.append(
            {
                "id": family_id,
                "title": family["title"],
                "areas": areas[family_id],
                "upstream_summary": family["upstream_summary"],
                "manuscripts": manuscripts,
                "lean": {
                    "status": status,
                    "doc": doc_url,
                    "comparators": comparator_rows,
                    "upstream_review_status": formalization["review_status"],
                    "scope": formalization["scope"],
                },
                "reasoning_trace": reasoning,
                "upstream_sha": commit,
            }
        )

    counts = count_families(built)
    counts["yaml_sources"] = len(source_slugs)
    counts["lean_docs"] = sum(1 for family in built if family["lean"]["doc"])
    counts["comparator_files"] = sum(
        1 for stem, suffixes in comparators.items() if suffixes == {"lean", "json"}
    )
    counts["main_result_rows"] = formalization["main_result_rows"]
    counts["reasoning_traces"] = sum(1 for family in built if family["reasoning_trace"])
    counts["areas"] = len(area_counts)
    readme_ok = (
        counts["families"] == readme_meta["families"]
        and counts["manuscripts"] == readme_meta["manuscripts"]
        and counts["families"] == headline_families
        and counts["manuscripts"] == headline_manuscripts
    )
    overview_ids = set(areas)
    content_ids = {family["id"] for family in built}
    if overview_ids != content_ids:
        raise AtlasError("overview.tex and CONTENTS.md name different families")
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "upstream": {
            "repo": UPSTREAM_WEB,
            "commit": commit,
            "readme_sentence": readme_meta["sentence"],
            "readme_families": readme_meta["families"],
            "readme_manuscripts": readme_meta["manuscripts"],
            "contents_families": headline_families,
            "contents_manuscripts": headline_manuscripts,
            "formalization_scope": formalization["scope"],
            "review_status": formalization["review_status"],
            "counts_match_readme": readme_ok,
        },
        "counts": counts,
        "areas": [{"name": name, "families": count} for name, count in area_counts],
        "families": built,
    }
    return payload, readme_ok


STATUS_COUNT_KEYS = {
    "main-result-formalized": "main_result_formalized",
    "comparator-challenge-only": "comparator_challenge_only",
    "none": "none",
}


def count_families(families: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "families": len(families),
        "manuscripts": sum(len(family["manuscripts"]) for family in families),
        "main_result_formalized": 0,
        "comparator_challenge_only": 0,
        "none": 0,
    }
    for family in families:
        status = family["lean"]["status"]
        key = STATUS_COUNT_KEYS.get(status)
        if key is None:
            raise AtlasError(f"unknown lean status {status}")
        counts[key] += 1
    return counts


def require_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AtlasError(f"{label} needs a non-empty string")
    return value.strip()


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def validate_curated_file(path: Path, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AtlasError(f"{path.name} must be a mapping")
    extra = set(payload) - CURATED_KEYS
    if extra:
        raise AtlasError(f"{path.name} has unknown fields: {sorted(extra)}")
    family_id = require_text(payload.get("id"), f"{path.name} id")
    if path.stem != family_id:
        raise AtlasError(f"{path.name} id is {family_id}")
    lenses = payload.get("lenses", [])
    related = payload.get("related", [])
    if not isinstance(lenses, list) or not isinstance(related, list):
        raise AtlasError(f"{path.name} lenses and related must be lists")
    clean_lenses = []
    for index, lens in enumerate(lenses, start=1):
        if not isinstance(lens, dict):
            raise AtlasError(f"{path.name} lens {index} must be a mapping")
        tag = require_text(lens.get("tag"), f"{path.name} lens {index} tag")
        if tag not in LENS_TAGS:
            raise AtlasError(f"{path.name} lens tag {tag} is not in the fixed list")
        why = require_text(lens.get("why"), f"{path.name} lens {index} why")
        source = require_text(lens.get("source"), f"{path.name} lens {index} source")
        clean_lenses.append({"tag": tag, "why": why, "source": source})
    clean_related = []
    for index, item in enumerate(related, start=1):
        if not isinstance(item, dict):
            raise AtlasError(f"{path.name} related {index} must be a mapping")
        target = require_text(item.get("to"), f"{path.name} related {index} to")
        kind = require_text(item.get("kind"), f"{path.name} related {index} kind")
        why = require_text(item.get("why"), f"{path.name} related {index} why")
        source = require_text(item.get("source"), f"{path.name} related {index} source")
        clean_related.append({"to": target, "kind": kind, "why": why, "source": source})
    community = payload.get("community")
    clean_community = None
    if community is not None:
        if not isinstance(community, dict):
            raise AtlasError(f"{path.name} community must be a mapping")
        status = require_text(community.get("status"), f"{path.name} community status")
        if status not in COMMUNITY_STATUSES:
            raise AtlasError(f"{path.name} community status {status} is unknown")
        evidence = community.get("evidence", [])
        if not isinstance(evidence, list):
            raise AtlasError(f"{path.name} evidence must be a list")
        if status in STATUSES_NEEDING_EVIDENCE and not evidence:
            raise AtlasError(f"{path.name} status {status} needs evidence")
        clean_evidence = []
        for index, item in enumerate(evidence, start=1):
            if not isinstance(item, dict):
                raise AtlasError(f"{path.name} evidence {index} must be a mapping")
            url = require_text(item.get("url"), f"{path.name} evidence {index} url")
            who = require_text(item.get("who"), f"{path.name} evidence {index} who")
            when = require_text(item.get("date"), f"{path.name} evidence {index} date")
            quote = require_text(item.get("quote"), f"{path.name} evidence {index} quote")
            if word_count(quote) > 25:
                raise AtlasError(f"{path.name} evidence {index} quote is over 25 words")
            source = item.get("source")
            if source is not None:
                source = require_text(source, f"{path.name} evidence {index} source")
            else:
                source = url
            clean_evidence.append(
                {"url": url, "who": who, "date": when, "quote": quote, "source": source}
            )
        clean_community = {"status": status, "evidence": clean_evidence}
    caution = payload.get("caution")
    clean_caution = None
    if caution is not None:
        if not isinstance(caution, dict):
            raise AtlasError(f"{path.name} caution must be a mapping with text and source")
        clean_caution = {
            "text": require_text(caution.get("text"), f"{path.name} caution text"),
            "source": require_text(caution.get("source"), f"{path.name} caution source"),
        }
    authored = json.dumps(
        {
            "lenses": clean_lenses,
            "related": clean_related,
            "community": clean_community,
            "caution": clean_caution,
        },
        ensure_ascii=False,
    )
    overclaims = scan_overclaims(authored, path.name)
    if overclaims:
        raise AtlasError(overclaims[0])
    return {
        "id": family_id,
        "lenses": clean_lenses,
        "related": clean_related,
        "community": clean_community,
        "caution": clean_caution,
    }


def load_curated(directory: Path) -> dict[str, dict[str, Any]]:
    loaded: dict[str, dict[str, Any]] = {}
    if not directory.is_dir():
        return loaded
    for path in sorted(directory.iterdir()):
        if path.suffix not in {".yaml", ".yml"}:
            continue
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        item = validate_curated_file(path, payload)
        if item["id"] in loaded:
            raise AtlasError(f"duplicate curated file for {item['id']}")
        loaded[item["id"]] = item
    return loaded


def load_cautions(path: Path) -> dict[str, dict[str, str]]:
    raw = read_json(path)
    cautions: dict[str, dict[str, str]] = {}
    if not isinstance(raw, dict):
        raise AtlasError("fixed cautions file must be a mapping")
    for family_id, item in raw.items():
        if not re.fullmatch(r"\d{3}", family_id):
            raise AtlasError(f"caution id {family_id} is not a family id")
        if not isinstance(item, dict):
            raise AtlasError(f"caution {family_id} must be a mapping")
        text = require_text(item.get("text"), f"caution {family_id} text")
        source = require_text(item.get("source"), f"caution {family_id} source")
        cautions[family_id] = {"text": text, "source": source}
    missing = [family_id for family_id in REQUIRED_CAUTION_IDS if family_id not in cautions]
    if missing:
        raise AtlasError(f"fixed cautions missing {missing}")
    for family_id, expected in REQUIRED_CAUTIONS.items():
        if cautions[family_id]["text"] != expected:
            raise AtlasError(f"fixed caution {family_id} text drifted")
    return cautions


REQUIRED_CAUTIONS = {
    "002": "BSD for low Selmer corank — not full BSD.",
    "003": "Zero-free region Re s > 7/8 ('quasi-Riemann hypothesis') — not the Riemann Hypothesis.",
    "032": "Hodge for CM abelian varieties — not the full Hodge conjecture.",
    "102": "Very large claims (UGC, L=RL, ω ≤ 9/4); treat as claims until checked.",
    "103": "Very large claims (UGC, L=RL, ω ≤ 9/4); treat as claims until checked.",
    "107": "Very large claims (UGC, L=RL, ω ≤ 9/4); treat as claims until checked.",
    "376": "Forced Navier–Stokes computation — not the Clay Millennium Navier–Stokes problem.",
}
REQUIRED_CAUTION_IDS = list(REQUIRED_CAUTIONS)


def merge_data(
    upstream: dict[str, Any],
    curated: dict[str, dict[str, Any]],
    cautions: dict[str, dict[str, str]],
) -> dict[str, Any]:
    known = {family["id"] for family in upstream["families"]}
    unknown = sorted(set(curated) - known)
    if unknown:
        raise AtlasError(f"curated files have no upstream family: {unknown}")
    merged_families = []
    for family in upstream["families"]:
        note = curated.get(family["id"])
        caution = cautions.get(family["id"], {}).get("text")
        if note and note["caution"]:
            extra = note["caution"]["text"]
            caution = extra if caution is None else f"{caution} {extra}"
        merged = dict(family)
        merged["caution"] = caution
        merged["lenses"] = note["lenses"] if note else []
        merged["related"] = note["related"] if note else []
        merged["community"] = note["community"] if note else None
        merged_families.append(merged)
    payload = {
        "schema_version": 1,
        "generated_at": upstream["generated_at"],
        "upstream": upstream["upstream"],
        "counts": upstream["counts"],
        "areas": upstream["areas"],
        "families": merged_families,
    }
    return payload


def assert_counts(payload: dict[str, Any]) -> None:
    families = payload["families"]
    counts = payload["counts"]
    derived = count_families(families)
    for key, value in derived.items():
        if counts.get(key) != value:
            raise AtlasError(f"count {key} is {counts.get(key)} in the file and {value} in the rows")
    if derived["main_result_formalized"] + derived["comparator_challenge_only"] + derived["none"] != derived["families"]:
        raise AtlasError("lean statuses do not add up to the family count")
    area_total = sum(area["families"] for area in payload["areas"])
    if area_total != derived["families"]:
        raise AtlasError("subject counts do not add up to the family count")
    upstream = payload["upstream"]
    if not upstream.get("counts_match_readme"):
        raise AtlasError("derived counts do not match the upstream README sentence")
    if derived["families"] != upstream["readme_families"] or derived["manuscripts"] != upstream["readme_manuscripts"]:
        raise AtlasError("derived counts do not match the stored README counts")
    if derived["families"] != upstream["contents_families"] or derived["manuscripts"] != upstream["contents_manuscripts"]:
        raise AtlasError("derived counts do not match the CONTENTS.md headline")
    commit = upstream["commit"]
    if commit == PINNED_COMMIT:
        for key, expected in PINNED_COUNTS.items():
            if counts.get(key) != expected:
                raise AtlasError(f"pinned count {key} is {counts.get(key)}, expected {expected}")
        ids = [family["id"] for family in families]
        missing = [f"{number:03d}" for number in range(1, 378) if f"{number:03d}" not in set(ids)]
        if missing != PINNED_MISSING_IDS:
            raise AtlasError(f"pinned missing ids are {missing}")
        areas = [(area["name"], area["families"]) for area in payload["areas"]]
        if areas != PINNED_AREAS:
            raise AtlasError("pinned subject counts drifted")
        if upstream["review_status"] != "unchecked":
            raise AtlasError("pinned formalization review status is not unchecked")


def sentence_key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip(".")


def allowed_caution_keys() -> set[str]:
    return {sentence_key(text) for text in REQUIRED_CAUTIONS.values()}


def prose_for_scan(text: str) -> str:
    blocked = re.sub(
        r"</(p|li|h[1-6]|tr|div|blockquote|section|article|td|th|dt|dd)>",
        ".",
        text,
        flags=re.IGNORECASE,
    )
    blocked = re.sub(r"<br\s*/?>", ".", blocked, flags=re.IGNORECASE)
    blocked = re.sub(r"(?m)^(#{1,6}[ \t]+\S.*)$", lambda match: match.group(1).rstrip() + ".", blocked)
    blocked = re.sub(r"<[^>]+>", " ", blocked)
    blocked = html.unescape(blocked)
    plain = blocked.replace("\n", " ")
    # Keep dotted R.H. inside one sentence. The topic pattern still matches either form.
    return re.sub(r"\bR\s*\.\s*H\s*\.", " RH ", plain, flags=re.IGNORECASE)


def scan_overclaims(text: str, label: str, extra_allowed: set[str] | None = None) -> list[str]:
    """Flag a sentence that names a guarded problem and uses a claim verb.

    A negation anywhere in the sentence is not an exemption. The only exemption
    is an exact fixed caution sentence.
    """
    allowed = allowed_caution_keys()
    if extra_allowed:
        allowed.update(sentence_key(item) for item in extra_allowed)
    failures = []
    for chunk in re.split(r"[.!?]+", prose_for_scan(text)):
        key = sentence_key(chunk)
        if not key or key in allowed:
            continue
        if CLAIM_TOPIC_RE.search(key) and CLAIM_VERB_RE.search(key):
            failures.append(f"{label}: {key[:180]}")
    return failures


def denylist_cores(token: str) -> set[str]:
    core = re.sub(r"^\d+|\d+$", "", re.sub(r"[^a-z0-9]", "", token))
    found: set[str] = set()
    pending = [core]
    while pending:
        current = pending.pop()
        if len(current) < DENYLIST_MIN_PREFIX or current in found:
            continue
        found.add(current)
        for suffix in DENYLIST_SUFFIXES:
            if current.endswith(suffix) and len(current) - len(suffix) >= DENYLIST_MIN_PREFIX:
                pending.append(current[: -len(suffix)])
    return found


def token_denied(token: str) -> bool:
    for core in denylist_cores(token):
        for length in range(DENYLIST_MIN_PREFIX, len(core) + 1):
            digest = hashlib.sha256(core[:length].encode()).hexdigest()
            if digest in DENYLIST_DIGESTS:
                return True
    return False


def denylist_hit(text: str) -> bool:
    lowered = text.lower()
    pieces = TOKEN_RE.findall(lowered)
    pieces.extend(re.sub(r"[^a-z0-9]", "", span) for span in HYPHEN_RUN_RE.findall(lowered))
    return any(token_denied(piece) for piece in pieces)


def authored_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "NOTICE", CAUTIONS_JSON]
    for directory in (ROOT / "src", CURATED_DIR):
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and path.suffix.lower() in {".astro", ".ts", ".css", ".js", ".md", ".yaml", ".yml", ".json"}:
                files.append(path)
    return files


def check_denylist_tree() -> list[str]:
    failures: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.suffix == ".pyc":
            continue
        if any(part in DENYLIST_SKIP for part in path.parts):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if denylist_hit(text):
            failures.append(f"{path.relative_to(ROOT)} contains a denylist token")
    return failures


def check_authored() -> list[str]:
    failures: list[str] = []
    for path in authored_files():
        text = path.read_text(encoding="utf-8")
        relative = str(path.relative_to(ROOT))
        failures.extend(scan_overclaims(text, relative))
    failures.extend(check_denylist_tree())
    return failures


def strip_upstream_quotes(html_text: str) -> str:
    without_quotes = re.sub(
        r"<blockquote\b[^>]*data-upstream[^>]*>.*?</blockquote>",
        "",
        html_text,
        flags=re.S,
    )
    return re.sub(r'\sdata-search="[^"]*"', "", without_quotes)


def check_dist(dist: Path) -> list[str]:
    failures: list[str] = []
    pages = sorted(dist.rglob("*.html"))
    if not pages:
        return [f"{dist} has no HTML"]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in pages)
    if denylist_hit(combined):
        failures.append("built site contains a denylist token")
    failures.extend(scan_overclaims(strip_upstream_quotes(combined), "built site"))
    index = dist / "index.html"
    about = dist / "about" / "index.html"
    if not index.is_file() or not about.is_file():
        failures.append("built site is missing the table or about page")
        return failures
    index_html = index.read_text(encoding="utf-8")
    about_html = about.read_text(encoding="utf-8")
    index_text = html.unescape(index_html)
    about_text = html.unescape(about_html)
    expected = read_json(FAMILIES_JSON)["counts"]
    family_ids = re.findall(r'id="f-(\d{3})"', index_html)
    if len(family_ids) != expected["families"] or len(set(family_ids)) != len(family_ids):
        failures.append(f"table renders {len(set(family_ids))} families, data has {expected['families']}")
    pdfs = re.findall(
        r'href="(https://github\.com/openai/math/blob/[0-9a-f]{40}/preprints/[^"]+)"',
        index_html,
    )
    if len(pdfs) != expected["manuscripts"]:
        failures.append(f"table renders {len(pdfs)} manuscript links, data has {expected['manuscripts']}")
    for family_id, text in REQUIRED_CAUTIONS.items():
        if text not in index_text:
            failures.append(f"table is missing the caution for {family_id}")
    for phrase in (
        "Not affiliated with OpenAI",
        "unchecked",
        "not a peer-reviewed paper",
        "not a laboratory result",
        "Apache-2.0",
        "We changed and derived these files",
    ):
        if phrase not in about_text:
            failures.append(f"about page is missing {phrase!r}")
    for page in pages:
        html_text = page.read_text(encoding="utf-8")
        if "https://github.com/openai/math" not in html_text:
            failures.append(f"{page.relative_to(dist)} has no upstream link")
        title = re.search(r"<title>([^<]*)</title>", html_text)
        heading = re.search(r"<h1[^>]*>([^<]*)</h1>", html_text)
        if title and re.search(r"openai", title.group(1), re.I):
            failures.append(f"{page.relative_to(dist)} title uses the upstream name")
        if heading and re.search(r"openai", heading.group(1), re.I):
            failures.append(f"{page.relative_to(dist)} heading uses the upstream name")
    return failures


def diff_summary(old: dict[str, Any] | None, new: dict[str, Any], curated_ids: set[str]) -> str:
    new_by_id = {family["id"]: family for family in new["families"]}
    if old is None:
        counts = new["counts"]
        return "\n".join(
            [
                "Initial catalogue import.",
                "",
                f"- Families: {counts['families']}",
                f"- Manuscripts: {counts['manuscripts']}",
                f"- Formalized main results: {counts['main_result_formalized']}",
                f"- Comparator challenge only: {counts['comparator_challenge_only']}",
                f"- No Lean formalization: {counts['none']}",
                "",
                f"README: {new['upstream']['readme_sentence']}",
                f"Counts match that sentence: {new['upstream']['counts_match_readme']}",
            ]
        )
    old_by_id = {family["id"]: family for family in old["families"]}
    added = sorted(set(new_by_id) - set(old_by_id))
    removed = sorted(set(old_by_id) - set(new_by_id))
    retitled = []
    summaries = []
    lean_changes = []
    manuscript_changes = []
    recheck = []
    for family_id in sorted(set(old_by_id) & set(new_by_id)):
        before = old_by_id[family_id]
        after = new_by_id[family_id]
        if before["title"] != after["title"]:
            retitled.append(family_id)
        if before["upstream_summary"] != after["upstream_summary"]:
            summaries.append(family_id)
            if family_id in curated_ids:
                recheck.append(family_id)
        if before["lean"]["status"] != after["lean"]["status"]:
            lean_changes.append(
                f"{family_id}: {before['lean']['status']} → {after['lean']['status']}"
            )
        before_slugs = {item["slug"] for item in before["manuscripts"]}
        after_slugs = {item["slug"] for item in after["manuscripts"]}
        if before_slugs != after_slugs:
            manuscript_changes.append(family_id)
    old_counts = old["counts"]
    new_counts = new["counts"]

    def preview(items: list[str]) -> str:
        if not items:
            return "none"
        shown = ", ".join(items[:20])
        if len(items) > 20:
            return f"{shown}, … ({len(items)})"
        return shown

    match = new["upstream"]["counts_match_readme"]
    lines = [
        f"Upstream sync `{old['upstream']['commit'][:12]}` → `{new['upstream']['commit'][:12]}`.",
        "",
        f"- Families: {old_counts['families']} → {new_counts['families']} (added {len(added)}, removed {len(removed)})",
        f"- Manuscripts: {old_counts['manuscripts']} → {new_counts['manuscripts']}",
        f"- Formalized main results: {old_counts['main_result_formalized']} → {new_counts['main_result_formalized']}",
        f"- Comparator challenge only: {old_counts['comparator_challenge_only']} → {new_counts['comparator_challenge_only']}",
        f"- No Lean formalization: {old_counts['none']} → {new_counts['none']}",
        f"- Added ids: {preview(added)}",
        f"- Removed ids: {preview(removed)}",
        f"- Retitled: {preview(retitled)}",
        f"- Summary text changes: {preview(summaries)}",
        f"- Manuscript set changes: {preview(manuscript_changes)}",
        f"- Lean status changes: {preview(lean_changes)}",
        f"- Curated families to re-check: {preview(recheck)}",
        "",
        f"README: {new['upstream']['readme_sentence']}",
        f"Counts match that sentence: {match}",
    ]
    if not match:
        lines.extend(
            [
                "",
                "The derived counts do not match the upstream README. Do not merge this PR.",
            ]
        )
    return "\n".join(lines)


def materialize_upstream(url: str, sha: str, dest: Path) -> None:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    if not (dest / ".git").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        subprocess.check_call(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--sparse",
                "--no-checkout",
                url,
                str(dest),
            ],
            env=env,
        )
    fetch = subprocess.run(
        ["git", "fetch", "--filter=blob:none", "--depth", "1", "origin", sha],
        cwd=dest,
        env=env,
        capture_output=True,
        text=True,
    )
    if fetch.returncode != 0:
        raise AtlasError(fetch.stderr.strip() or "git fetch failed")
    subprocess.run(["git", "sparse-checkout", "init", "--no-cone"], cwd=dest, check=False)
    subprocess.check_call(["git", "sparse-checkout", "set", "--no-cone", *SPARSE_PATHS], cwd=dest)
    subprocess.check_call(["git", "checkout", "--detach", "FETCH_HEAD"], cwd=dest)
    got = git(dest, "rev-parse", "HEAD").strip()
    if got != sha:
        raise AtlasError(f"fetched {got}, expected {sha}")
