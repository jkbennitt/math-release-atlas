"""Parse the upstream catalogue, merge hand-written notes, and check claims."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import struct
import subprocess
import tempfile
import unicodedata
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
PREVIEW_IMAGE_NAME = "og.png"
PREVIEW_WIDTH = 1200
PREVIEW_HEIGHT = 630


def preview_alt(families: int, manuscripts: int) -> str:
    """Sentence on the card image and in og:image:alt. Keep it free of claim verbs."""
    return (
        f"Math Release Atlas: {families} result families and {manuscripts} manuscripts. Unofficial."
    )

LENS_ORDER = (
    "condensed-matter",
    "plasma-kinetic",
    "fluids-continuum",
    "electronic-structure",
    "quantum-information",
    "gravity-qft",
    "computation-hardness",
)
LENS_TAGS = set(LENS_ORDER)
COMMUNITY_STATUS_FILE = CURATED_DIR / "community-status.yaml"
STATUS_APPROVALS_FILE = CURATED_DIR / "status-approvals.yaml"
STATUS_APPROVER = "jkbennitt"
COMMUNITY_STATUSES = {
    "claimed",
    "community-checking",
    "independently-checked",
    "disputed",
    "retracted",
}
STATUSES_NEEDING_EVIDENCE = COMMUNITY_STATUSES - {"claimed"}
COMMUNITY_KEYS = {"status", "evidence", "history"}
EVIDENCE_KEYS = {"url", "date", "note"}
HISTORY_KEYS = {"status", "date", "note", "url"}
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
    "/preprints/**/*.tex",
    "/preprints/**/*.bib",
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

# A sentence is an overclaim when the guarded problem itself is what the claim verb
# addresses. RH and dotted R.H. are normalized before the split. Riemann's hypothesis
# is included, including a hyphen in place of the space. Clay and Millennium count
# when they name the problem or the prize, with a hyphen or a space.
# The incompressible-flow name does not count when the next word is one of the
# qualifiers below, unless the sentence also uses wording for the Clay problem itself.
# Space, ASCII hyphen, hyphen, non-breaking hyphen, figure dash, en dash,
# em dash, minus, and fullwidth hyphen. The same class separates Navier and Stokes.
_SEP = r"[\s\-\u2010\u2011\u2012\u2013\u2014\u2212\uff0d]"
PROBLEM_RE = re.compile(
    rf"(?P<flow>navier{_SEP}*stokes)"
    rf"|(?P<name>(?:quasi{_SEP}+)?riemann(?:['\u2019]s)?{_SEP}+hypothesis|\brh\b|\br\s+h\b"
    rf"|clay{_SEP}+(?:millennium{_SEP}+)?(?:problem|prize)"
    rf"|millennium{_SEP}+(?:problem|prize))",
    re.IGNORECASE,
)
FLOW_QUALIFIER_RE = re.compile(
    r"\s+(?:energy|inequalit(?:y|ies)|estimates?|bounds?|"
    r"computations?|schemes?|solvers?|approximations?)\b",
    re.IGNORECASE,
)
# Words that name the Clay problem itself. Any one of them disables the qualifier exception.
# blow and up may be joined by a space, hyphen, or dash. "smooth data" does not cancel
# unless the sentence also has a claim verb. "smoothness" still cancels.
FLOW_CLAY_WORDING_RE = re.compile(
    rf"\b(?:regularity|smoothness|smooth(?!\s+data)|blow{_SEP}*up|existence|well{_SEP}*posed(?:ness)?)\b",
    re.IGNORECASE,
)
FLOW_CLAY_WORDING_WITH_CLAIM_RE = re.compile(
    rf"\b(?:regularity|smooth(?:ness)?|blow{_SEP}*up|existence|well{_SEP}*posed(?:ness)?)\b",
    re.IGNORECASE,
)
# Main's sentence-level noun checks, unchanged. There is no word boundary
# before "proof", so "disproof of" matches. These fire anywhere in a sentence
# that names a guarded problem. The proximity rule is an additional check.
_SENTENCE_NOUN_RE = re.compile(
    r"proofs?\s+(?:of|for|complete)|\bsolutions?\s+(?:to|of)\b",
    re.IGNORECASE,
)
# A comma-separated aside between solution and to/of, as in
# "solution, long sought by many, to". This is not one of main's checks.
_SOLUTION_ASIDE_RE = re.compile(
    r"\bsolutions?\s*,[^.]{0,80},\s*(?:to|of)\b",
    re.IGNORECASE,
)
# A claim noun within four tokens of a guarded problem name is also a claim,
# in either order. Punctuation and possessives are ignored. A whole-sentence
# allowlist may waive solution or solutions. It never waives a proof compound.
_CLAIM_NOUNS = frozenset(
    {"proof", "proofs", "disproof", "disproofs", "solution", "solutions", "resolution", "resolved"}
)
_NOUN_QUALIFIERS = frozenset(
    {
        "scheme",
        "operator",
        "numerical",
        "weak",
        "leray",
        "mild",
        "strong",
        "assistant",
        "lemma",
        "estimate",
        "estimates",
        "approximate",
    }
)
_NOUN_PROXIMITY = 4
_QUALIFIER_BEFORE = "|".join(sorted(_NOUN_QUALIFIERS, key=len, reverse=True))
# Template A endings stay empty. A must-pass phrase that needs words after the
# flow name is the only way an entry is added, and none of them do.
_TEMPLATE_A_ENDINGS: tuple[str, ...] = ()
_TEMPLATE_A_ENDING = (
    "(?:\\s+(?:" + "|".join(re.escape(item) for item in _TEMPLATE_A_ENDINGS) + "))?"
    if _TEMPLATE_A_ENDINGS
    else ""
)
# Whole sentence, after the flow name is folded to "navier-stokes".
# Optional article, qualifier, solution(s) of/to, optional "the", the name,
# optional equations or system, and nothing else.
_TEMPLATE_A_RE = re.compile(
    rf"^(?:(?:a|an|the)\s+)?(?:{_QUALIFIER_BEFORE})\s+solutions?\s+(?:of|to)\s+"
    rf"(?:the\s+)?navier-stokes(?:\s+(?:equations|system))?{_TEMPLATE_A_ENDING}$"
)
# Name first. This waives only the four-token check, never a main-pattern match.
_TEMPLATE_B_RE = re.compile(
    r"^(?:(?:a|an|the)\s+)?navier-stokes\s+solutions?\s+"
    r"(?:schemes|scheme|operators|operator|methods|method)"
    r"(?:\s+(?:is|are)\s+bounded)?$"
)
# prove/proves/proved/proving/proven, disprove/disproves/disproved/disproving/disproven,
# proof of/for, proof complete (also the same words inside disproof),
# confirm/confirms/confirmed/confirming,
# establish/establishes/established/establishing, a solution to, solution of,
# resolve/resolves/resolved/resolving, settle/settles/settled/settling,
# solve/solves/solved/solving, crack/cracks/cracked/cracking,
# finish/finishes/finished/finishing,
# true, holds, follows, verify/verifies/verified/verifying, a theorem,
# show/shows/showed/shown/showing, demonstrate/demonstrates/demonstrated/demonstrating,
# win/wins/won/winning, award/awards/awarded/awarding, correct,
# obtain/obtains/obtained/obtaining, done.
CLAIM_VERB_RE = re.compile(
    r"\bproven\b|\bprov(?:e|es|ed|ing)\b|\bdisprov(?:en|e|es|ed|ing)\b|"
    r"\bconfirm(?:ed|s|ing)?\b|"
    + _SENTENCE_NOUN_RE.pattern
    + r"|\bestablish(?:es|ed|ing)?\b|"
    r"\bresolv(?:e|es|ed|ing)\b|\bsettl(?:e|es|ed|ing)\b|"
    r"\bsolv(?:e|es|ed|ing)\b|\bcrack(?:s|ed|ing)?\b|"
    r"\bfinish(?:es|ed|ing)?\b|"
    r"\btrue\b|\bholds\b|\bfollows\b|\bverif(?:y|ies|ied|ying)\b|"
    r"\ba\s+theorem\b|"
    r"\bshow(?:n|s|ed|ing)?\b|\bdemonstrat(?:e|es|ed|ing)\b|"
    r"\bwins?\b|\bwon\b|\bwinning\b|\baward(?:ed|s|ing)?\b|\bcorrect\b|"
    r"\bobtain(?:s|ed|ing)?\b|\bdone\b",
    re.IGNORECASE,
)
OAI_CITE_RE = re.compile(r"OAI:([A-Za-z0-9][A-Za-z0-9_.+\-]*)")
EVIDENCE_URL_RE = re.compile(r"https?://[^\s\"<>`]+", re.IGNORECASE)
# SHA-256 of data/upstream.json for PINNED_COMMIT, ignoring generated_at.
PINNED_UPSTREAM_DIGEST = "9f34421e815eb47d11bcb4463801f35649b02656abc141e277a5ae581ed648ac"
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
# Full-string digests for compounds shorter than DENYLIST_MIN_PREFIX, or compounds
# whose pieces are ordinary words. Matched exactly, never as a prefix.
COMPOUND_DIGESTS = frozenset(
    {
        "31f879daf4b5f4e69ebbecd000a39cd49fbe3e6fa24b7e5f1d64ee9f8af74d91",
        "865414b13b4f62b39deb69c52e451cabcc12a8470a4ea63b1c161aa8801599c3",
        "42acd0c18cb4977c2ea8ce0aaf3ddeca0882a02a2e02e20a69cea57116a85c7f",
    }
)
# The length-6 stem may sit beside a math term. Those neighbor digests are not stems.
# A preceding neighbor excuses the stem only when no word follows it.
NEIGHBOR_STEM_DIGEST = "f5d36c673cea1d80af3d33404d506e0c3e7aeaa0b8c1a21e085fa3caa8928b3b"
NEIGHBOR_AFTER_DIGESTS = frozenset(
    {
        "a6216ea03e578f212dd604ec5d675c5274a86891bac4e87f80bea10ef511f533",
        "edb2cd3b74c999af70f0b7054990f2072dc6e10a847af6ed05954b8994b730fe",
    }
)
NEIGHBOR_BEFORE_DIGESTS = frozenset(
    {
        "a2bf2be47b9cf824068bfcfacbb4594af68031393e433099ed9240cc0fd707c9",
    }
)
DENYLIST_MIN_PREFIX = 6
DENYLIST_SUFFIXES = ("ivity", "ing", "ers", "ion", "ors", "ive", "es", "ed", "ly", "al", "s")
TOKEN_RE = re.compile(r"[a-z0-9]+")
HYPHEN_RUN_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)+")
DENYLIST_SKIP = {".git", "node_modules", "dist", ".astro", "__pycache__", ".playwright-mcp"}
ATTR_RE = re.compile(
    r"""\b(?P<name>alt|title|content|aria-label|aria-description|placeholder|data-[\w-]+)\s*=\s*(?:"(?P<dq>[^"]*)"|'(?P<sq>[^']*)'|(?P<uq>[^\s"'=<>`]+))""",
    re.IGNORECASE,
)
# SHA-256 of hostile note tokens. The words are not stored here.
NOTE_HOSTILE_DIGESTS = frozenset(
    {
        "795b6904e54f82411df4b0e27a373a55eea3f9d66dac5a9bce1dd92f7b401da5",
        "f02b95ed0b00ce45335979782615d60879b99e788fa3b7b8fca1599589b88846",
        "02ed3adf622abdf4749a343e948e6b5fbe32f2f2a9eca0811e46235b13de6e86",
        "de5d4b32ca829a6e3e27a3cf23812f5111352589d4c9291edf3274c6d78943ff",
        "30e9190d7fdfc50d3621e24455a9eafed652c8571a7ddabf75018c1fbe9d73a9",
        "487225c5b1d422991e2218a325ef283ccb259a4e2ca4437bb72ab59add480a12",
        "1d932876a62ceefa7832711b0d27e902c083ee30db1c538bebd0d54440e0a86f",
        "b5d54c39e66671c9731b9f471e585d8262cd4f54963f0c93082d8dcf334d4c78",
        "48fab7a56479b7ec15bd571024dee1cdfe85678289c5cca3ed95769793797c6e",
        "ef995d2472a252c1fddfcac544dc596b462d25dbd4905dded35480246529b6cf",
        "0083289f36deda0724d899ac2d13042efaa70d38073e49780d2b30bce4dadca0",
        "c2820752d64e02b086fec967badc27a5e12b12ededb5a117eff29b667ec01559",
        "f3c16f525a1b7c204fc953d6d7db7168d84ebf4902f83c3a37d113b18c28981f",
        "a4542449353f0b0aef8deaeab784b0e946072c7a65e1f468d7dffd88da4a1901",
        "b4648e44d84988892ec93710b15bb8f6b053054b0c40d48a04f783d0daca5ffd",
        "19465de87beffcfac5fc83680a38d2d75c2a1049d6d5d08ced533beb930a2c39",
        "ef875a1705a5fdac206be996f4dc1f726ea6b68861eb741c37def7277f179e37",
        "82d928273d067d774889d5df4249aaf73c0b04c64f04d6ed001441ce87a0853c",
        "cacc6bcf3a66ea9b2b6ede264ad98a6a91c2844efe312e2aedaca8a3931349c7",
        "3a1b45d4778cc8a6e07420119952efa34e7ffd44ffe01d3726d501824d5f51b9",
        "3734f204b6669b3125d0e7a551413dda2b5bec48fffdc3f9a5010f9ad0413f51",
        "87654be893e93c6552e800afb313c7e4ea0f345c8c575211a91baa07bed5a107",
        "b028fac88cf83c2a2f0e4f04e02cbf823c8d2179f92c41d813df95e5ee152adf",
        "f514ae60147922b97e8d1bed3e4bb3b108366876cc77fff92b0ee181fd16d9cc",
        "2d48a24e8e8bd908b53d8ab81e7ca6320d50e5ce3260d522b549d4b02a8b308f",
        "6cf2bed0023c84a655f6aeba6f404f6674b03c061e5297462262ec5f07804e4b",
        "d9b4323e416218d2514eca2acd82410ed976d4815bd7cf798208e28408f3213d",
    }
)
NOTE_HOSTILE_PHRASE_DIGEST = "3dedd643819c6059145438295590f166326d20c812fff8971bbd627078626fd1"
# Whole tokens the inflection rule would otherwise split into a hostile stem.
NOTE_ALLOW_TOKEN_DIGESTS = frozenset(
    {
        "2737596a7a48877e6afaa9719940a6d0c548e875b8ee72cbe389f1fcc0d442c7",
    }
)
# Two-word technical phrases whose first word would otherwise match a hostile token.
NOTE_EXEMPT_PHRASE_DIGESTS = frozenset(
    {
        "4f76b35955d6c947426a2f9fce18cc84c6368723c0e0d46817451e4b2280556f",
        "fd753b0edd3df7d9657bf426696cf94b640c37c50953a2213685586829ae8b4f",
        "99f60348c017becd964023ead3d29334482b6278c8379b5905f34fabb033c247",
    }
)
# Hyphenated technical compounds. Any other hyphenated compound is checked.
NOTE_EXEMPT_HYPHEN_DIGESTS = frozenset(
    {
        "b0515c3530385ed70aab8811467b5cd73ad2007389384959e3d232f8a1fabf60",
        "418f827bfd243359b42239c005cc21ab487cbee409904f9b61644b799ade00b1",
        "aa45363e9c06f52ac87b1a7a461015183cf2879806ddf8abed403d39b16ee77b",
        "c74b0d8465d47e3d11949fb1fbf9a5aa7868f09ad418b1d8d3cdd4c436622965",
    }
)
NOTE_SUFFIXES = ("ing", "ers", "ed", "ly")
NOTE_STEM_MIN = 4
# Soft hyphen and zero-width characters. Removed before the denylist and claim checks.
INVISIBLE_RE = re.compile("[\u00ad\u200b\u200c\u200d\u2060\ufeff\u180e]")
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


def attach_citations(repo: Path, commit: str, families: list[dict[str, Any]]) -> None:
    """Record one directed edge per family pair cited via an OAI: manuscript key.

    The receipt is the first .tex or .bib path in sorted order. A family citing
    its own manuscript is not an edge. Keys that are not manuscript slugs are ignored.
    """
    slug_to: dict[str, str] = {}
    for family in families:
        for manuscript in family["manuscripts"]:
            slug_to[manuscript["slug"]] = family["id"]
    edges: dict[tuple[str, str], dict[str, str]] = {}
    root = repo / "preprints"
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in {".tex", ".bib"}:
                continue
            rel = path.relative_to(repo).as_posix()
            parts = rel.split("/")
            if len(parts) < 3 or parts[0] != "preprints":
                continue
            owner = slug_to.get(parts[1])
            if owner is None:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            for key in OAI_CITE_RE.findall(text):
                target = slug_to.get(key)
                if target is None or target == owner:
                    continue
                edges.setdefault(
                    (owner, target),
                    {
                        "to": target,
                        "via": f"OAI:{key}",
                        "source": rel,
                        "url": blob_url(commit, rel),
                    },
                )
    by_from: dict[str, list[dict[str, str]]] = defaultdict(list)
    for (src, _dst), edge in edges.items():
        by_from[src].append(edge)
    for family in families:
        family["citations"] = sorted(
            by_from.get(family["id"], []),
            key=lambda edge: (edge["to"], edge["source"]),
        )


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

    attach_citations(repo, commit, built)
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


def require_day(value: str, label: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise AtlasError(f"{label} must be YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError:
        raise AtlasError(f"{label} must be YYYY-MM-DD") from None
    return value


def require_http_url(value: str, label: str) -> str:
    if EVIDENCE_URL_RE.fullmatch(value) is None:
        raise AtlasError(f"{label} must be an http(s) URL")
    return value


def require_note(value: Any, label: str) -> str:
    note = require_text(value, label)
    if word_count(note) > 25:
        raise AtlasError(f"{label} is over 25 words")
    if note_tone_failure(note):
        raise AtlasError(f"{label} is not a neutral note")
    return note


def parse_evidence_item(path: Path, index: int, item: Any) -> dict[str, str]:
    label = f"{path.name} evidence {index}"
    if not isinstance(item, dict):
        raise AtlasError(f"{label} must be a mapping")
    extra = set(item) - EVIDENCE_KEYS
    if extra:
        raise AtlasError(f"{label} has unknown fields: {sorted(extra)}")
    return {
        "url": require_http_url(require_text(item.get("url"), f"{label} url"), f"{label} url"),
        "date": require_day(require_text(item.get("date"), f"{label} date"), f"{label} date"),
        "note": require_note(item.get("note"), f"{label} note"),
    }


def parse_history_item(path: Path, index: int, item: Any) -> dict[str, str]:
    label = f"{path.name} history {index}"
    if not isinstance(item, dict):
        raise AtlasError(f"{label} must be a mapping")
    extra = set(item) - HISTORY_KEYS
    if extra:
        raise AtlasError(f"{label} has unknown fields: {sorted(extra)}")
    status = require_text(item.get("status"), f"{label} status")
    if status not in COMMUNITY_STATUSES:
        raise AtlasError(f"{label} status {status} is unknown")
    cleaned = {
        "status": status,
        "date": require_day(require_text(item.get("date"), f"{label} date"), f"{label} date"),
        "note": require_note(item.get("note"), f"{label} note"),
    }
    url = item.get("url")
    if status in STATUSES_NEEDING_EVIDENCE:
        cleaned["url"] = require_http_url(require_text(url, f"{label} url"), f"{label} url")
    elif url is not None:
        cleaned["url"] = require_http_url(require_text(url, f"{label} url"), f"{label} url")
    return cleaned


def parse_community(path: Path, community: Any) -> dict[str, Any] | None:
    if community is None:
        return None
    if not isinstance(community, dict):
        raise AtlasError(f"{path.name} community must be a mapping")
    extra = set(community) - COMMUNITY_KEYS
    if extra:
        raise AtlasError(f"{path.name} community has unknown fields: {sorted(extra)}")
    status = require_text(community.get("status"), f"{path.name} community status")
    if status not in COMMUNITY_STATUSES:
        raise AtlasError(f"{path.name} community status {status} is unknown")
    evidence = community.get("evidence", [])
    if not isinstance(evidence, list):
        raise AtlasError(f"{path.name} evidence must be a list")
    if status in STATUSES_NEEDING_EVIDENCE and not evidence:
        raise AtlasError(f"{path.name} status {status} needs evidence")
    history = community.get("history", [])
    if not isinstance(history, list):
        raise AtlasError(f"{path.name} history must be a list")
    return {
        "status": status,
        "evidence": [parse_evidence_item(path, index, item) for index, item in enumerate(evidence, start=1)],
        "history": [parse_history_item(path, index, item) for index, item in enumerate(history, start=1)],
    }


def load_community_schema(path: Path) -> dict[str, Any]:
    """The vocabulary file is the contract. Ids must match the guard exactly."""
    if not path.is_file():
        raise AtlasError("community status schema is missing")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise AtlasError("community status schema must be a mapping")
    rows = payload.get("vocabulary")
    if not isinstance(rows, list) or not rows:
        raise AtlasError("community status schema needs a vocabulary")
    ids: list[str] = []
    needing: set[str] = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            raise AtlasError(f"community status {index} must be a mapping")
        status_id = require_text(row.get("id"), f"community status {index}")
        evidence = require_text(row.get("evidence"), f"community status {status_id} evidence")
        if evidence not in {"required", "optional"}:
            raise AtlasError(f"community status {status_id} evidence must be required or optional")
        ids.append(status_id)
        if evidence == "required":
            needing.add(status_id)
    if len(ids) != len(set(ids)) or set(ids) != COMMUNITY_STATUSES:
        raise AtlasError("community status vocabulary does not match the guard")
    if needing != STATUSES_NEEDING_EVIDENCE:
        raise AtlasError("community status evidence rules do not match the guard")
    rule = require_text(payload.get("rule"), "community status rule")
    if "must be approved by Jason (repo policy)" not in rule:
        raise AtlasError("community status rule must state the repo policy")
    return payload


def load_status_approvals(path: Path) -> list[dict[str, str]]:
    """Allowlist entries that let a non-claimed status pass Guard.

    The file starts empty. A later pull request adds one entry per evidence URL.
    """
    if not path.is_file():
        raise AtlasError("status approvals file is missing")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise AtlasError("status approvals must be a mapping")
    extra = set(payload) - {"approvals"}
    if extra:
        raise AtlasError(f"status approvals has unknown fields: {sorted(extra)}")
    rows = payload.get("approvals")
    if not isinstance(rows, list):
        raise AtlasError("status approvals must be a list")
    cleaned: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str, str, str]] = set()
    for index, row in enumerate(rows, start=1):
        label = f"status approval {index}"
        if not isinstance(row, dict):
            raise AtlasError(f"{label} must be a mapping")
        unknown = set(row) - {"id", "status", "url", "date", "note", "approver"}
        if unknown:
            raise AtlasError(f"{label} has unknown fields: {sorted(unknown)}")
        family_id = require_text(row.get("id"), f"{label} id")
        if not re.fullmatch(r"\d{3}", family_id):
            raise AtlasError(f"{label} id must be a family id")
        status = require_text(row.get("status"), f"{label} status")
        if status not in STATUSES_NEEDING_EVIDENCE:
            raise AtlasError(f"{label} status {status} does not need an approval")
        url = require_http_url(require_text(row.get("url"), f"{label} url"), f"{label} url")
        day = require_day(require_text(row.get("date"), f"{label} date"), f"{label} date")
        note = require_note(row.get("note"), f"{label} note")
        approver = require_text(row.get("approver"), f"{label} approver")
        if approver != STATUS_APPROVER:
            raise AtlasError(f"{label} approver must be {STATUS_APPROVER}")
        key = (family_id, status, url, day, note, approver)
        if key in seen:
            raise AtlasError(f"{label} repeats an earlier entry")
        seen.add(key)
        cleaned.append(
            {
                "id": family_id,
                "status": status,
                "url": url,
                "date": day,
                "note": note,
                "approver": approver,
            }
        )
    return cleaned


def approval_mismatches(curated: dict[str, dict[str, Any]], approvals: list[dict[str, str]]) -> list[str]:
    """A non-claimed status passes only when id, status, URL, date, note, and approver all match."""
    approved = {
        (row["id"], row["status"], row["url"], row["date"], row["note"], row["approver"]) for row in approvals
    }
    used: set[tuple[str, str, str, str, str, str]] = set()
    failures: list[str] = []
    for family_id, item in sorted(curated.items()):
        community = item.get("community")
        if not community:
            continue
        refs: list[tuple[str, str, str, str]] = []
        status = community.get("status")
        if status in STATUSES_NEEDING_EVIDENCE:
            evidence = [entry for entry in community.get("evidence") or [] if isinstance(entry, dict)]
            if not evidence:
                failures.append(f"{family_id} status {status} is not on the approval allowlist")
            for entry in evidence:
                refs.append((status, str(entry.get("url")), str(entry.get("date")), str(entry.get("note"))))
        for event in community.get("history") or []:
            if not isinstance(event, dict):
                continue
            event_status = event.get("status")
            if event_status in STATUSES_NEEDING_EVIDENCE and event.get("url"):
                refs.append(
                    (str(event_status), str(event.get("url")), str(event.get("date")), str(event.get("note")))
                )
        for event_status, url, day, note in refs:
            key = (family_id, event_status, url, day, note, STATUS_APPROVER)
            if key not in approved:
                failures.append(f"{family_id} status {event_status} is not on the approval allowlist")
            else:
                used.add(key)
    for family_id, status, _url, _day, _note, _approver in sorted(approved - used):
        failures.append(f"unused status approval for {family_id} {status}")
    return failures


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
    clean_community = parse_community(path, payload.get("community"))
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
    # json.dumps escapes a newline, so scan the why and caution strings raw too.
    prose_parts = [authored]
    prose_parts.extend(item["why"] for item in clean_lenses)
    prose_parts.extend(item["why"] for item in clean_related)
    if clean_caution is not None:
        prose_parts.append(clean_caution["text"])
    overclaims = scan_overclaims("\n".join(prose_parts), path.name)
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
        if path.name in {COMMUNITY_STATUS_FILE.name, STATUS_APPROVALS_FILE.name}:
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
    apply_citation_graph(merged_families)
    payload = {
        "schema_version": 1,
        "generated_at": upstream["generated_at"],
        "upstream": upstream["upstream"],
        "counts": upstream["counts"],
        "areas": upstream["areas"],
        "families": merged_families,
    }
    return payload


def apply_citation_graph(families: list[dict[str, Any]]) -> None:
    """Project upstream citation edges into cites and cited_by. Does not invent a status."""
    incoming: dict[str, list[dict[str, str]]] = defaultdict(list)
    known = {family["id"] for family in families}
    for family in families:
        raw = family.pop("citations", [])
        if not isinstance(raw, list):
            raise AtlasError(f"family {family['id']} citations must be a list")
        cites: list[dict[str, str]] = []
        for edge in raw:
            if not isinstance(edge, dict):
                raise AtlasError(f"family {family['id']} has a citation that is not a mapping")
            target = edge.get("to")
            if target not in known:
                raise AtlasError(f"family {family['id']} cites unknown family {target}")
            item = {
                "to": str(edge["to"]),
                "via": str(edge["via"]),
                "source": str(edge["source"]),
                "url": str(edge["url"]),
            }
            cites.append(item)
            incoming[str(target)].append(
                {
                    "from": family["id"],
                    "via": item["via"],
                    "source": item["source"],
                    "url": item["url"],
                }
            )
        family["cites"] = cites
    for family in families:
        family["cited_by"] = sorted(
            incoming.get(family["id"], []),
            key=lambda edge: (edge["from"], edge["source"]),
        )


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


def snapshot_for_compare(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "generated_at"}


def snapshot_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        snapshot_for_compare(payload),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode()).hexdigest()


def describe_snapshot_diff(recorded: dict[str, Any], rebuilt: dict[str, Any]) -> str:
    notes: list[str] = []
    for key in ("upstream", "counts", "areas"):
        if recorded.get(key) != rebuilt.get(key):
            notes.append(key)
    recorded_rows = {family["id"]: family for family in recorded.get("families", [])}
    rebuilt_rows = {family["id"]: family for family in rebuilt.get("families", [])}
    changed = [
        family_id
        for family_id in sorted(set(recorded_rows) | set(rebuilt_rows))
        if recorded_rows.get(family_id) != rebuilt_rows.get(family_id)
    ]
    if changed:
        shown = ", ".join(changed[:12])
        extra = f" (+{len(changed) - 12})" if len(changed) > 12 else ""
        notes.append(f"families {shown}{extra}")
    return "; ".join(notes) or "content"


def assert_upstream_digest(payload: dict[str, Any]) -> None:
    """The stored digest applies to the pinned commit.

    A different commit is not accepted just because the digest check returns.
    verify_recorded_upstream and sync.py require it to be openai/math HEAD
    or an ancestor of that HEAD.
    """
    commit = payload.get("upstream", {}).get("commit")
    if commit != PINNED_COMMIT:
        return
    if snapshot_digest(payload) != PINNED_UPSTREAM_DIGEST:
        raise AtlasError("pinned upstream snapshot digest drifted")


def assert_merged_catalogue(
    upstream: dict[str, Any],
    families: dict[str, Any],
    curated: dict[str, dict[str, Any]],
    cautions: dict[str, dict[str, str]],
) -> None:
    merged = merge_data(upstream, curated, cautions)
    if merged != families:
        raise AtlasError("families.json is not the merge of upstream.json and the curated notes")


def verify_recorded_upstream() -> None:
    """Rebuild data/upstream.json from the commit it names and fail on any difference.

    The commit must be openai/math HEAD or an ancestor of it. generated_at is a
    timestamp and is ignored. The checkout is a sparse fetch of that commit, the
    same path the daily sync uses. A fetch or network failure is an AtlasError.
    """
    recorded = read_json(UPSTREAM_JSON)
    commit = str(recorded.get("upstream", {}).get("commit", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise AtlasError("upstream.json has no commit sha")
    try:
        with tempfile.TemporaryDirectory(prefix="atlas-upstream-") as tmp:
            checkout = Path(tmp)
            materialize_upstream(UPSTREAM_URL, commit, checkout)
            rebuilt, _ = build_upstream(checkout)
    except subprocess.CalledProcessError as exc:
        raise git_failure(exc.stderr or exc.stdout or "", "could not fetch upstream") from None
    if snapshot_for_compare(recorded) != snapshot_for_compare(rebuilt):
        detail = describe_snapshot_diff(snapshot_for_compare(recorded), snapshot_for_compare(rebuilt))
        raise AtlasError(f"upstream.json differs from commit {commit}: {detail}")


def sentence_key(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().rstrip(".")


def allowed_caution_keys() -> set[str]:
    return {sentence_key(text) for text in REQUIRED_CAUTIONS.values()}


def normalize_scan_text(text: str) -> str:
    """NFKC-normalize and drop soft hyphens and zero-width characters."""
    return unicodedata.normalize("NFKC", INVISIBLE_RE.sub("", text))


def attribute_text(text: str) -> str:
    """Authored attribute values, each as its own sentence.

    Every data-* value is scanned. Built HTML blanks a value first when it
    exactly equals that family's upstream title or id.
    """
    parts: list[str] = []
    for match in ATTR_RE.finditer(text):
        value = match.group("dq") or match.group("sq") or match.group("uq") or ""
        if value:
            parts.append(value)
    return ". ".join(parts)


def prose_for_scan(text: str) -> str:
    text = normalize_scan_text(text)
    comments = " ".join(re.findall(r"<!--(.*?)-->", text, flags=re.DOTALL))
    attributes = attribute_text(text)
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
    if attributes:
        plain = f"{plain}. {html.unescape(attributes)}"
    if comments:
        plain = f"{plain}. {html.unescape(comments)}"
    # Keep dotted R.H. inside one sentence. The topic pattern still matches either form.
    return re.sub(r"\bR\s*\.\s*H\s*\.", " RH ", plain, flags=re.IGNORECASE)


def _claim_tokens(text: str) -> list[str]:
    """Lowercase tokens with punctuation and possessives removed."""
    lowered = text.lower().replace("\u2019", "'")
    lowered = re.sub(r"(?<=[a-z])'s\b", "", lowered)
    return [token for token in re.split(r"[^a-z0-9]+", lowered) if token]


def _problem_token_spans(tokens: list[str]) -> list[tuple[int, int, str]]:
    """Half-open spans of guarded names. The third item is "flow" or "name".

    "flow" is Navier–Stokes, including the unseparated form. "name" is RH,
    the spaced form R H, the Riemann Hypothesis, Clay, or Millennium.
    """
    spans: list[tuple[int, int, str]] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token == "riemann" and index + 1 < len(tokens) and tokens[index + 1] == "hypothesis":
            spans.append((index, index + 2, "name"))
            index += 2
            continue
        if token == "r" and index + 1 < len(tokens) and tokens[index + 1] == "h":
            spans.append((index, index + 2, "name"))
            index += 2
            continue
        if token == "navier" and index + 1 < len(tokens) and tokens[index + 1] == "stokes":
            spans.append((index, index + 2, "flow"))
            index += 2
            continue
        if token == "navierstokes":
            spans.append((index, index + 1, "flow"))
            index += 1
            continue
        if token in {"rh", "clay", "millennium"}:
            spans.append((index, index + 1, "name"))
            index += 1
            continue
        index += 1
    return spans


def _gap_to_span(index: int, start: int, end: int) -> int:
    if start <= index < end:
        return -1
    return start - index - 1 if index < start else index - end


def _allowlist_text(sentence: str) -> str:
    """Lowercase, drop trailing punctuation, and fold every spelling of the flow name.

    ASCII hyphen, hyphen, non-breaking hyphen, figure dash, en dash, em dash,
    minus, fullwidth hyphen, a space, and no separator at all all become
    navier-stokes before a template is applied.
    """
    text = sentence_key(sentence).casefold()
    text = text.rstrip(".,;:!?\"'")
    text = re.sub(rf"navier{_SEP}*stokes", "navier-stokes", text)
    return re.sub(r"\s+", " ", text).strip()


def _matches_template_a(sentence: str) -> bool:
    return _TEMPLATE_A_RE.match(_allowlist_text(sentence)) is not None


def _matches_template_b(sentence: str) -> bool:
    return _TEMPLATE_B_RE.match(_allowlist_text(sentence)) is not None


def _rescued_main_spans(sentence: str) -> set[tuple[int, int]]:
    """Main solution spans rescued by template A.

    Template B never rescues these spans. A proof compound is never rescued.
    The caller requires this set to equal every main match.
    """
    if not _matches_template_a(sentence):
        return set()
    rescued: set[tuple[int, int]] = set()
    for main in _SENTENCE_NOUN_RE.finditer(sentence):
        if re.fullmatch(r"solutions?\s+(?:to|of)", main.group(), flags=re.IGNORECASE):
            rescued.add(main.span())
    return rescued


def _other_claim_verb(sentence: str) -> bool:
    """True when a claim remains after main's two noun patterns are removed."""
    return CLAIM_VERB_RE.search(_SENTENCE_NOUN_RE.sub(" ", sentence)) is not None


def sentence_level_claim(sentence: str) -> bool:
    """Main's proof-of and solution-of checks, plus template A.

    The two patterns are unchanged. A match is rescued only when the whole
    sentence matches template A and the match is solution or solutions followed
    by to or of. Template B does not rescue these matches. Proof, disproof, and
    any other proof compound are never rescued. If the rescued positions are
    not exactly the main matches, one unrescued match fails the sentence,
    including a match inside counterproof or foolproof.
    """
    if CLAIM_VERB_RE.search(sentence) is None or not mentions_guarded_problem(sentence):
        return False
    if _other_claim_verb(sentence):
        return True
    matches = list(_SENTENCE_NOUN_RE.finditer(sentence))
    if not matches:
        return False
    rescued = _rescued_main_spans(sentence)
    return len(rescued) != len(matches) or {match.span() for match in matches} != rescued


def solution_aside_claim(sentence: str) -> bool:
    """A comma-separated aside before to/of is not the technical-solution rescue."""
    return _SOLUTION_ASIDE_RE.search(sentence) is not None and mentions_guarded_problem(sentence)


def proximate_claim_noun(sentence: str) -> bool:
    """True when a claim noun sits within four tokens of a guarded problem name.

    solution or solutions may be waived only when the whole sentence matches
    template A or template B and the name is the incompressible-flow name.
    Template B waives this check only. proof, disproof, and any other proof
    compound are never waived. "proof assistant" is not a claim noun.
    """
    tokens = _claim_tokens(sentence)
    spans = _problem_token_spans(tokens)
    if not spans:
        return False
    allow_proximity = _matches_template_a(sentence) or _matches_template_b(sentence)
    for index, token in enumerate(tokens):
        if token not in _CLAIM_NOUNS:
            continue
        if token in {"proof", "proofs"} and index + 1 < len(tokens) and tokens[index + 1] == "assistant":
            continue
        for start, end, kind in spans:
            gap = _gap_to_span(index, start, end)
            if gap < 0 or gap > _NOUN_PROXIMITY:
                continue
            rescued = (
                allow_proximity
                and kind == "flow"
                and token in {"solution", "solutions"}
            )
            if not rescued:
                return True
    return False


def mentions_guarded_problem(sentence: str) -> bool:
    """True when the problem itself is named, not when the name only modifies another noun."""
    has_claim = CLAIM_VERB_RE.search(sentence) is not None
    clay = FLOW_CLAY_WORDING_WITH_CLAIM_RE if has_claim else FLOW_CLAY_WORDING_RE
    blocks_flow_exception = clay.search(sentence) is not None
    for match in PROBLEM_RE.finditer(sentence):
        qualified = FLOW_QUALIFIER_RE.match(sentence[match.end() :]) is not None
        if match.group("flow") and qualified and not blocks_flow_exception:
            continue
        return True
    return False


def scan_overclaims(text: str, label: str, extra_allowed: set[str] | None = None) -> list[str]:
    """Flag a sentence that claims a guarded problem itself was proved, solved, or settled.

    A negation anywhere in the sentence is not an exemption. The only exemption
    is an exact fixed caution sentence. A flow name followed by energy, an
    inequality, an estimate, a bound, a computation, a scheme, a solver, or an
    approximation is not the guarded problem, unless the sentence also says
    regularity, smoothness, smooth (except when the next word is data), blow up,
    blow-up, blowup, existence, well-posed, or well-posedness. When a claim verb
    is also present, smooth cancels that exception even if the next word is data.
    A space, hyphen, or dash may separate blow and up, or well and posed.
    proof or disproof followed by of, for, or complete, and solution or
    solutions followed by to or of, fail anywhere in the sentence. A match is
    rescued only when the whole sentence matches template A: an optional
    article, a technical qualifier, solution or solutions, of or to, an
    optional "the", the incompressible-flow name, and an optional equations or
    system, with no other words. Every hyphen, dash, space, and joined spelling
    of that name is folded first. Proof, disproof, and any other proof compound
    are never rescued. Template B does not rescue these matches. If the rescued
    positions are not exactly the main matches, the sentence fails. A claim
    noun within four tokens of a guarded problem name also fails, in either
    order. Punctuation and possessives are ignored. That nearer check waives
    solution or solutions only when the whole sentence matches template A or
    template B. Template B is an optional article, the flow name, solution or
    solutions, then scheme, schemes, operator, operators, method, or methods,
    then an optional "is bounded" or "are bounded". alt, title, content,
    aria-label, aria-description, placeholder, and data-* attributes are scanned
    with the prose, including unquoted values. Text nodes inside a data-upstream
    element are left out only when that element's text exactly equals the
    family's upstream title, id, summary, or manuscript title. Attributes on
    that element and its descendants are still scanned. HTML comments are
    scanned as well, including comments left inside an exempt element.
    """
    allowed = allowed_caution_keys()
    if extra_allowed:
        allowed.update(sentence_key(item) for item in extra_allowed)
    failures = []
    for chunk in re.split(r"[.!?]+", prose_for_scan(text)):
        key = sentence_key(chunk)
        if not key or key in allowed:
            continue
        if sentence_level_claim(key) or proximate_claim_noun(key) or solution_aside_claim(key):
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


def _digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hostile_token(token: str) -> bool:
    """Whole-word match, plus a plural or inflection of a stored stem."""
    if _digest(token) in NOTE_ALLOW_TOKEN_DIGESTS:
        return False
    if _digest(token) in NOTE_HOSTILE_DIGESTS:
        return True
    for suffix in NOTE_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= NOTE_STEM_MIN:
            if _digest(token[: -len(suffix)]) in NOTE_HOSTILE_DIGESTS:
                return True
    if token.endswith("es") and len(token) - 2 >= NOTE_STEM_MIN:
        stem = token[:-2]
        if stem.endswith(("s", "x", "z", "ch", "sh")) and _digest(stem) in NOTE_HOSTILE_DIGESTS:
            return True
    if token.endswith("s") and not token.endswith("ss") and len(token) - 1 >= NOTE_STEM_MIN:
        if _digest(token[:-1]) in NOTE_HOSTILE_DIGESTS:
            return True
    return False


def note_tone_failure(note: str) -> bool:
    """True when a note contains a hostile word, inflection, or the stored phrase.

    A stored hyphenated technical compound is left alone. Any other hyphenated
    compound fails when a part is hostile or the joined parts are hostile.
    Adjacent words that join into a hostile word fail too. A stored two-word
    technical phrase is left alone. A stored whole token is left alone when the
    inflection rule would split it into a hostile stem.
    """
    lowered = normalize_scan_text(note).lower()
    exempt_spans: list[tuple[int, int]] = []
    for match in HYPHEN_RUN_RE.finditer(lowered):
        if _digest(match.group()) in NOTE_EXEMPT_HYPHEN_DIGESTS:
            exempt_spans.append((match.start(), match.end()))
            continue
        parts = match.group().split("-")
        if any(hostile_token(part) for part in parts) or hostile_token("".join(parts)):
            return True
    tokens: list[tuple[str, bool]] = []
    for match in TOKEN_RE.finditer(lowered):
        inside_exempt = any(start <= match.start() and match.end() <= end for start, end in exempt_spans)
        tokens.append((match.group(), inside_exempt))
    words = [token for token, _inside in tokens]
    exempt: set[int] = set()
    for index in range(len(words) - 1):
        if _digest(f"{words[index]} {words[index + 1]}") in NOTE_EXEMPT_PHRASE_DIGESTS:
            exempt.add(index)
            exempt.add(index + 1)
    for index in range(len(words) - 2):
        if _digest(" ".join(words[index : index + 3])) == NOTE_HOSTILE_PHRASE_DIGEST:
            return True
    for index in range(len(words) - 1):
        if index in exempt or index + 1 in exempt or tokens[index][1] or tokens[index + 1][1]:
            continue
        if hostile_token(words[index] + words[index + 1]):
            return True
    for index, (token, inside_exempt) in enumerate(tokens):
        if inside_exempt or index in exempt:
            continue
        if hostile_token(token):
            return True
    return False


def neighbor_compound_excused(core: str) -> bool:
    """A collapsed math compound whose first six letters are the stem and whose tail is a neighbor."""
    if len(core) <= DENYLIST_MIN_PREFIX:
        return False
    if _digest(core[:DENYLIST_MIN_PREFIX]) != NEIGHBOR_STEM_DIGEST:
        return False
    return _digest(core[DENYLIST_MIN_PREFIX:]) in NEIGHBOR_AFTER_DIGESTS


def neighbor_token_excused(pieces: list[str], index: int) -> bool:
    if _digest(pieces[index]) != NEIGHBOR_STEM_DIGEST:
        return False
    following = pieces[index + 1] if index + 1 < len(pieces) else ""
    if following and _digest(following) in NEIGHBOR_AFTER_DIGESTS:
        return True
    preceding = pieces[index - 1] if index > 0 else ""
    if preceding and _digest(preceding) in NEIGHBOR_BEFORE_DIGESTS and not following:
        return True
    return False


def hyphen_run_excused(parts: list[str]) -> bool:
    if len(parts) != 2:
        return False
    if _digest(parts[0]) == NEIGHBOR_STEM_DIGEST and _digest(parts[1]) in NEIGHBOR_AFTER_DIGESTS:
        return True
    if _digest(parts[1]) == NEIGHBOR_STEM_DIGEST and _digest(parts[0]) in NEIGHBOR_BEFORE_DIGESTS:
        return True
    return False


def token_denied(token: str) -> bool:
    core = re.sub(r"[^a-z0-9]", "", token.lower())
    if core and _digest(core) in COMPOUND_DIGESTS:
        return True
    if neighbor_compound_excused(core):
        return False
    for stem in denylist_cores(token):
        for length in range(DENYLIST_MIN_PREFIX, len(stem) + 1):
            if _digest(stem[:length]) in DENYLIST_DIGESTS:
                return True
    return False


def denylist_hit(text: str) -> bool:
    lowered = normalize_scan_text(text).lower()
    pieces = TOKEN_RE.findall(lowered)
    for left, right in zip(pieces, pieces[1:]):
        if _digest(left + right) in COMPOUND_DIGESTS:
            return True
    for span in HYPHEN_RUN_RE.findall(lowered):
        parts = span.split("-")
        collapsed = "".join(parts)
        if _digest(collapsed) in COMPOUND_DIGESTS:
            return True
        if hyphen_run_excused(parts):
            continue
        if token_denied(collapsed):
            return True
    for index, piece in enumerate(pieces):
        if neighbor_token_excused(pieces, index):
            continue
        if token_denied(piece):
            return True
    return False


def authored_files() -> list[Path]:
    files = [ROOT / "README.md", ROOT / "NOTICE", ROOT / "CONTRIBUTING.md", CAUTIONS_JSON]
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
    """Scan prose we wrote. Upstream titles and summaries are not part of the sentence check.

    The digest check covers the whole tree, including the generated snapshot.
    """
    failures: list[str] = []
    for path in authored_files():
        text = path.read_text(encoding="utf-8")
        relative = str(path.relative_to(ROOT))
        failures.extend(scan_overclaims(text, relative))
    failures.extend(check_denylist_tree())
    return failures


def strip_upstream_quotes(html_text: str) -> str:
    """Drop elements that quote the upstream catalogue. The claim check no longer uses this."""
    without_quotes = re.sub(
        r"<(?P<tag>[a-z0-9]+)\b[^>]*\bdata-upstream\b[^>]*>.*?</(?P=tag)>",
        " ",
        html_text,
        flags=re.S | re.IGNORECASE,
    )
    return re.sub(r'\sdata-search="[^"]*"', "", without_quotes)


def check_family_pages(dist: Path, families: list[dict[str, Any]], index_html: str) -> list[str]:
    failures: list[str] = []
    index_text = html.unescape(index_html)
    for family in families:
        if f"f/{family['id']}/" not in index_html:
            failures.append(f"table does not link to family {family['id']}")
        page = dist / "f" / family["id"] / "index.html"
        if not page.is_file():
            failures.append(f"missing family page f/{family['id']}/")
            continue
        text = html.unescape(page.read_text(encoding="utf-8"))
        if family["title"] not in text:
            failures.append(f"family page {family['id']} is missing its title")
        for area in family["areas"]:
            if area not in text:
                failures.append(f"family page {family['id']} is missing subject {area}")
        if "Community status" not in text:
            failures.append(f"family page {family['id']} is missing community status")
        status = (family.get("community") or {}).get("status") or "claimed"
        if status == "claimed" and "Claimed" not in text:
            failures.append(f"family page {family['id']} does not show the default claimed status")
        if family["upstream_sha"] not in text:
            failures.append(f"family page {family['id']} is missing the upstream commit")
        if "Status history" not in text:
            failures.append(f"family page {family['id']} is missing status history")
        if "Cites" not in text or "Cited by" not in text:
            failures.append(f"family page {family['id']} is missing citation lists")
        for edge in family.get("cites") or []:
            if edge["url"] not in text or f"f/{edge['to']}/" not in text:
                failures.append(f"family page {family['id']} is missing cite {edge['to']}")
        for edge in family.get("cited_by") or []:
            if edge["url"] not in text or f"f/{edge['from']}/" not in text:
                failures.append(f"family page {family['id']} is missing cited-by {edge['from']}")
        for lens in family.get("lenses") or []:
            if lens["tag"] not in text or lens["source"] not in text:
                failures.append(f"family page {family['id']} is missing lens {lens['tag']}")
        caution = family.get("caution")
        if caution and caution not in text:
            failures.append(f"family page {family['id']} is missing its caution")
        summary = family.get("upstream_summary") or ""
        if summary and summary not in text:
            failures.append(f"family page {family['id']} is missing its upstream summary")
        if summary and summary not in index_text:
            failures.append(f"table is missing the upstream summary for {family['id']}")
        for item in family["manuscripts"]:
            if item["pdf"] not in text or item["date"] not in text or item["title"] not in text:
                failures.append(f"family page {family['id']} is missing manuscript {item['slug']}")
            if item["title"] not in index_text:
                failures.append(f"table is missing manuscript title for {family['id']}")
    return failures


def check_lens_pages(dist: Path, families: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    index = dist / "lens" / "index.html"
    if not index.is_file():
        return ["missing lens index"]
    index_text = index.read_text(encoding="utf-8")
    grouped: dict[str, list[str]] = {tag: [] for tag in LENS_ORDER}
    for family in families:
        for lens in family.get("lenses") or []:
            grouped.setdefault(lens["tag"], []).append(family["id"])
    for tag in LENS_ORDER:
        if f"lens/{tag}/" not in index_text:
            failures.append(f"lens index does not link to {tag}")
        page = dist / "lens" / tag / "index.html"
        if not page.is_file():
            failures.append(f"missing lens page {tag}")
            continue
        text = page.read_text(encoding="utf-8")
        for family_id in grouped.get(tag, []):
            if f"f/{family_id}/" not in text:
                failures.append(f"lens page {tag} is missing family {family_id}")
    return failures


def citation_pairs(payload: dict[str, Any]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for family in payload.get("families") or []:
        for edge in family.get("citations") or []:
            pairs.add((family["id"], edge.get("to")))
    return pairs


def check_graph_page(dist: Path, families: list[dict[str, Any]]) -> list[str]:
    page = dist / "graph" / "index.html"
    if not page.is_file():
        return ["missing citation graph"]
    text = html.unescape(page.read_text(encoding="utf-8"))
    failures: list[str] = []
    if "our grouping, not a citation" not in text:
        failures.append("citation graph does not label shared-topic links")
    if "<ul" not in text:
        failures.append("citation graph has no list fallback")
    for family in families:
        for edge in family.get("cites") or []:
            if edge["url"] not in text or f"f/{family['id']}/" not in text or f"f/{edge['to']}/" not in text:
                failures.append(f"citation graph is missing {family['id']} → {edge['to']}")
        for item in family.get("related") or []:
            if item.get("kind") == "shared-topic" and f"f/{item['to']}/" not in text:
                failures.append(f"citation graph is missing shared-topic {family['id']} → {item['to']}")
    return failures


_UPSTREAM_ELEMENT_RE = re.compile(
    r"<(?P<tag>[a-z0-9]+)\b(?P<attrs>[^>]*\bdata-upstream\b[^>]*)>(?P<body>.*?)</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)


def visible_element_text(body: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()


def blank_text_nodes(body: str) -> str:
    """Drop text nodes and keep every tag, including attributes on descendants."""
    return "".join(part for part in re.split(r"(<[^>]*>)", body) if part.startswith("<"))


def exempt_upstream_text(html_text: str, allowed: set[str]) -> str:
    """Blank text nodes of a data-upstream element whose text equals an allowed string.

    Attributes on that element and on elements inside it stay in the scan.
    """
    normalized = {re.sub(r"\s+", " ", item).strip() for item in allowed if item}

    def replacer(match: re.Match[str]) -> str:
        if visible_element_text(match.group("body")) not in normalized:
            return match.group(0)
        return (
            f"<{match.group('tag')}{match.group('attrs')}>"
            f"{blank_text_nodes(match.group('body'))}"
            f"</{match.group('tag')}>"
        )

    return _UPSTREAM_ELEMENT_RE.sub(replacer, html_text)


def family_scan_identity(family: dict[str, Any]) -> set[str]:
    """Upstream title, id, summary, and manuscript titles.

    A rendered data-upstream value is exempt only when it equals one of these.
    Text that does not match stays on the page and fails the check.
    """
    allowed = {family["id"]}
    for value in (family.get("title"), family.get("upstream_summary")):
        if isinstance(value, str) and value:
            allowed.add(value)
    for item in family.get("manuscripts") or []:
        manuscript_title = item.get("title") if isinstance(item, dict) else None
        if isinstance(manuscript_title, str) and manuscript_title:
            allowed.add(manuscript_title)
    return allowed


def blank_exempt_data_values(html_text: str, allowed: set[str]) -> str:
    """Blank data-* values that exactly equal an allowed upstream string."""

    def replacer(match: re.Match[str]) -> str:
        name = match.group("name").lower()
        if not name.startswith("data-"):
            return match.group(0)
        raw = match.group("dq")
        if raw is None:
            raw = match.group("sq")
        if raw is None:
            raw = match.group("uq") or ""
        if html.unescape(raw) not in allowed:
            return match.group(0)
        if match.group("dq") is not None:
            return f'{match.group("name")}=""'
        if match.group("sq") is not None:
            return f"{match.group('name')}=''"
        return f'{match.group("name")}='

    return ATTR_RE.sub(replacer, html_text)


_INDEX_ROW_RE = re.compile(
    r'<tr\b(?=[^>]*\bid="f-(?P<id>\d{3})")[^>]*>.*?</tr>',
    re.IGNORECASE | re.DOTALL,
)


def exempt_index_rows(html_text: str, families: list[dict[str, Any]]) -> str:
    """On the catalogue table, exempt data-* values only inside that family's row."""
    by_id = {family["id"]: family for family in families}

    def replacer(match: re.Match[str]) -> str:
        family = by_id.get(match.group("id"))
        if family is None:
            return match.group(0)
        allowed = family_scan_identity(family)
        return exempt_upstream_text(blank_exempt_data_values(match.group(0), allowed), allowed)

    return _INDEX_ROW_RE.sub(replacer, html_text)


def prepare_built_page(path: Path, dist: Path, families: list[dict[str, Any]]) -> str:
    """Apply the per-family data-* exemption before the sentence scan."""
    html_text = path.read_text(encoding="utf-8")
    relative = path.relative_to(dist)
    parts = relative.parts
    by_id = {family["id"]: family for family in families}
    if len(parts) >= 2 and parts[0] == "f" and re.fullmatch(r"\d{3}", parts[1]):
        family = by_id.get(parts[1])
        if family is not None:
            allowed = family_scan_identity(family)
            return exempt_upstream_text(blank_exempt_data_values(html_text, allowed), allowed)
    if relative.as_posix() == "index.html":
        return exempt_index_rows(html_text, families)
    return exempt_upstream_by_family_link(html_text, families)


def exempt_upstream_by_family_link(html_text: str, families: list[dict[str, Any]]) -> str:
    """On lens pages, exempt a title only inside the link for that family."""
    by_id = {family["id"]: family_scan_identity(family) for family in families}

    def replacer(match: re.Match[str]) -> str:
        window = html_text[max(0, match.start() - 800) : match.start()]
        found = re.findall(r'(?:id="f-|/f/)(\d{3})', window)
        allowed = by_id.get(found[-1], set()) if found else set()
        if visible_element_text(match.group("body")) not in {re.sub(r"\s+", " ", item).strip() for item in allowed}:
            return match.group(0)
        return (
            f"<{match.group('tag')}{match.group('attrs')}>"
            f"{blank_text_nodes(match.group('body'))}"
            f"</{match.group('tag')}>"
        )

    return _UPSTREAM_ELEMENT_RE.sub(replacer, html_text)


def check_status_page(dist: Path, families: list[dict[str, Any]]) -> list[str]:
    page = dist / "status" / "index.html"
    if not page.is_file():
        return ["missing community status page"]
    text = html.unescape(page.read_text(encoding="utf-8"))
    failures: list[str] = []
    for phrase in (
        "claimed",
        "community-checking",
        "independently-checked",
        "disputed",
        "retracted",
        "must be approved by Jason (repo policy)",
        "status-approvals.yaml",
        "jkbennitt",
    ):
        if phrase not in text:
            failures.append(f"status page is missing {phrase!r}")
    for family in families:
        community = family.get("community") or {}
        status = community.get("status") or "claimed"
        if status != "claimed" and f"f/{family['id']}/" not in text:
            failures.append(f"status page is missing family {family['id']}")
    return failures


_ATTR_RE = re.compile(r"""([^\s=/>]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_META_RE = re.compile(r"<meta\b([^>]*)>", re.IGNORECASE)
_LINK_RE = re.compile(r"<link\b([^>]*)>", re.IGNORECASE)
_TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.IGNORECASE)


def published_prefix() -> str:
    """Absolute origin plus the Pages base path, with a trailing slash."""
    text = (ROOT / "astro.config.mjs").read_text(encoding="utf-8")
    site = re.search(r'site:\s*"([^"]+)"', text)
    base = re.search(r'base:\s*"([^"]+)"', text)
    if site is None or base is None:
        return ""
    return f"{site.group(1).rstrip('/')}/{base.group(1).strip('/')}/"


def preview_image_url(prefix: str) -> str:
    return f"{prefix}{PREVIEW_IMAGE_NAME}"


def _tag_attrs(blob: str) -> dict[str, str]:
    attrs: dict[str, str] = {}
    for match in _ATTR_RE.finditer(blob):
        value = match.group(2) if match.group(2) is not None else match.group(3)
        attrs[match.group(1).lower()] = html.unescape(value)
    return attrs


def social_meta(html_text: str) -> dict[str, Any]:
    properties: dict[str, str] = {}
    names: dict[str, str] = {}
    for match in _META_RE.finditer(html_text):
        attrs = _tag_attrs(match.group(1))
        content = attrs.get("content", "")
        if "property" in attrs:
            properties[attrs["property"]] = content
        if "name" in attrs:
            names[attrs["name"]] = content
    canonical = ""
    for match in _LINK_RE.finditer(html_text):
        attrs = _tag_attrs(match.group(1))
        if attrs.get("rel") == "canonical":
            canonical = attrs.get("href", "")
            break
    title_match = _TITLE_RE.search(html_text)
    title = html.unescape(title_match.group(1)).strip() if title_match else ""
    return {"properties": properties, "names": names, "canonical": canonical, "title": title}


def _absolute_failure(url: str, label: str, field: str, prefix: str) -> str | None:
    if not url.lower().startswith("https://"):
        return f"{label} {field} is not absolute"
    if not prefix or not url.startswith(prefix):
        return f"{label} {field} is missing the site base path"
    return None


def check_social_preview(
    html_text: str,
    label: str,
    prefix: str,
    counts: dict[str, Any] | None = None,
) -> list[str]:
    """Fail when a built page cannot produce a large-image link preview."""
    tags = social_meta(html_text)
    properties: dict[str, str] = tags["properties"]
    names: dict[str, str] = tags["names"]
    failures: list[str] = []
    required_properties = (
        "og:title",
        "og:description",
        "og:url",
        "og:type",
        "og:site_name",
        "og:image",
        "og:image:width",
        "og:image:height",
        "og:image:alt",
    )
    for key in required_properties:
        if not properties.get(key, "").strip():
            failures.append(f"{label} is missing {key}")
    for key in ("twitter:card", "twitter:title", "twitter:description", "twitter:image"):
        if not names.get(key, "").strip():
            failures.append(f"{label} is missing {key}")
    image = properties.get("og:image", "").strip()
    image_failure = _absolute_failure(image, label, "og:image", prefix) if image else None
    if image_failure:
        failures.append(image_failure)
    elif image and prefix and image != preview_image_url(prefix):
        failures.append(f"{label} og:image is not the shared preview")
    for field, url in (
        ("og:url", properties.get("og:url", "").strip()),
        ("twitter:image", names.get("twitter:image", "").strip()),
        ("canonical", tags["canonical"].strip()),
    ):
        if not url:
            if field == "canonical":
                failures.append(f"{label} is missing canonical")
            continue
        failure = _absolute_failure(url, label, field, prefix)
        if failure:
            failures.append(failure)
    if names.get("twitter:card", "").strip() and names.get("twitter:card") != "summary_large_image":
        failures.append(f"{label} twitter:card is not summary_large_image")
    if properties.get("og:type", "").strip() and properties.get("og:type") != "website":
        failures.append(f"{label} og:type is not website")
    if properties.get("og:site_name", "").strip() and properties.get("og:site_name") != "Math Release Atlas":
        failures.append(f"{label} og:site_name is not the atlas name")
    if properties.get("og:image:width", "").strip() and properties.get("og:image:width") != str(PREVIEW_WIDTH):
        failures.append(f"{label} og:image:width is not {PREVIEW_WIDTH}")
    if properties.get("og:image:height", "").strip() and properties.get("og:image:height") != str(PREVIEW_HEIGHT):
        failures.append(f"{label} og:image:height is not {PREVIEW_HEIGHT}")
    title = tags["title"]
    if properties.get("og:title", "").strip() and properties.get("og:title") != title:
        failures.append(f"{label} og:title does not match the page title")
    description = names.get("description", "")
    if properties.get("og:description", "").strip() and properties.get("og:description") != description:
        failures.append(f"{label} og:description does not match the page description")
    if names.get("twitter:title", "").strip() and names.get("twitter:title") != title:
        failures.append(f"{label} twitter:title does not match the page title")
    if names.get("twitter:description", "").strip() and names.get("twitter:description") != description:
        failures.append(f"{label} twitter:description does not match the page description")
    if names.get("twitter:image", "").strip() and image and names.get("twitter:image") != image:
        failures.append(f"{label} twitter:image does not match og:image")
    if tags["canonical"].strip() and properties.get("og:url", "").strip() and tags["canonical"] != properties.get("og:url"):
        failures.append(f"{label} canonical does not match og:url")
    if counts is not None and properties.get("og:image:alt", "").strip():
        expected = preview_alt(int(counts["families"]), int(counts["manuscripts"]))
        if properties.get("og:image:alt") != expected:
            failures.append(f"{label} og:image:alt does not match the catalogue counts")
        twitter_alt = names.get("twitter:image:alt", "")
        if twitter_alt and twitter_alt != expected:
            failures.append(f"{label} twitter:image:alt does not match the catalogue counts")
    return failures


def png_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def check_preview_image(dist: Path) -> list[str]:
    path = dist / PREVIEW_IMAGE_NAME
    if not path.is_file():
        return ["built site is missing og.png"]
    size = png_dimensions(path.read_bytes())
    if size != (PREVIEW_WIDTH, PREVIEW_HEIGHT):
        return [f"og.png is {size}, expected {PREVIEW_WIDTH}x{PREVIEW_HEIGHT}"]
    return []


def check_named_previews(dist: Path) -> list[str]:
    """Home, graph, and status each carry their own title and description."""
    expected = {
        "index.html": "Math Release Atlas",
        "graph/index.html": "Citation graph",
        "status/index.html": "Community status",
    }
    failures: list[str] = []
    titles: list[str] = []
    descriptions: list[str] = []
    for relative, mark in expected.items():
        path = dist / relative
        if not path.is_file():
            failures.append(f"missing preview page {relative}")
            continue
        tags = social_meta(path.read_text(encoding="utf-8"))
        title = tags["title"]
        description = tags["names"].get("description", "").strip()
        if relative == "index.html":
            if title != mark:
                failures.append(f"{relative} preview title is {title!r}")
        elif mark not in title:
            failures.append(f"{relative} preview title does not name the page")
        if not description:
            failures.append(f"{relative} is missing a description")
        titles.append(title)
        descriptions.append(description)
    if len(titles) == 3 and (len(set(titles)) != 3 or len(set(descriptions)) != 3):
        failures.append("home, graph, and status share a preview title or description")
    return failures


def check_link_previews(dist: Path) -> list[str]:
    failures: list[str] = []
    pages = sorted(path for path in dist.rglob("*.html") if path.is_file())
    prefix = published_prefix()
    if not prefix:
        failures.append("astro.config.mjs is missing site or base")
    counts = None
    if FAMILIES_JSON.is_file():
        try:
            counts = read_json(FAMILIES_JSON)["counts"]
        except (OSError, json.JSONDecodeError, KeyError):
            failures.append("catalogue counts are unreadable for the preview check")
    for page in pages:
        label = page.relative_to(dist).as_posix()
        failures.extend(check_social_preview(page.read_text(encoding="utf-8"), label, prefix, counts))
    failures.extend(check_preview_image(dist))
    failures.extend(check_named_previews(dist))
    return failures


def check_preview_source() -> list[str]:
    """Preview tags are emitted once, from the layout, and the card reads the counts."""
    failures: list[str] = []
    layout = (ROOT / "src" / "layouts" / "Base.astro").read_text(encoding="utf-8")
    if 'property="og:image"' not in layout or 'name="twitter:card"' not in layout:
        failures.append("layout does not emit preview tags")
    if 'content="summary_large_image"' not in layout or 'rel="canonical"' not in layout:
        failures.append("layout does not emit a large-image card and a canonical URL")
    for path in (ROOT / "src" / "pages").rglob("*.astro"):
        text = path.read_text(encoding="utf-8")
        if "og:image" in text or "twitter:card" in text:
            failures.append(f"{path.relative_to(ROOT)} duplicates preview tags")
    card = (ROOT / "scripts" / "og_card.py").read_text(encoding="utf-8")
    if 'counts["families"]' not in card or 'counts["manuscripts"]' not in card:
        failures.append("preview card does not read catalogue counts")
    for name in (
        "AtlasCardSerif-Regular.ttf",
        "AtlasCardSerif-Bold.ttf",
        "AtlasCardSans-Regular.ttf",
        "OFL.txt",
    ):
        if not (ROOT / "scripts" / "fonts" / name).is_file():
            failures.append(f"missing preview font file {name}")
    return failures


def check_dist(dist: Path) -> list[str]:
    failures: list[str] = []
    pages = sorted(dist.rglob("*.html"))
    if not pages:
        return [f"{dist} has no HTML"]
    failures.extend(check_link_previews(dist))
    combined = "\n".join(path.read_text(encoding="utf-8") for path in pages)
    if denylist_hit(combined):
        failures.append("built site contains a denylist token")
    if "not shown on this page" in html.unescape(combined):
        failures.append("built site hides upstream text")
    index = dist / "index.html"
    about = dist / "about" / "index.html"
    if not index.is_file() or not about.is_file():
        failures.append("built site is missing the table or about page")
        failures.extend(scan_overclaims(combined, "built site"))
        return failures
    catalog = read_json(FAMILIES_JSON)
    prepared = "\n".join(prepare_built_page(path, dist, catalog["families"]) for path in pages)
    failures.extend(scan_overclaims(prepared, "built site"))
    index_html = index.read_text(encoding="utf-8")
    about_html = about.read_text(encoding="utf-8")
    index_text = html.unescape(index_html)
    about_text = html.unescape(about_html)
    expected = catalog["counts"]
    family_ids = re.findall(r'id="f-(\d{3})"', index_html)
    if len(family_ids) != expected["families"] or len(set(family_ids)) != len(family_ids):
        failures.append(f"table renders {len(set(family_ids))} families, data has {expected['families']}")
    pdfs = re.findall(
        r'href="(https://github\.com/openai/math/blob/[0-9a-f]{40}/preprints/[^"]+)"',
        index_html,
    )
    if len(pdfs) != expected["manuscripts"]:
        failures.append(f"table renders {len(pdfs)} manuscript links, data has {expected['manuscripts']}")
    failures.extend(check_family_pages(dist, catalog["families"], index_html))
    failures.extend(check_lens_pages(dist, catalog["families"]))
    failures.extend(check_graph_page(dist, catalog["families"]))
    failures.extend(check_status_page(dist, catalog["families"]))
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
    old_edges = citation_pairs(old)
    new_edges = citation_pairs(new)
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
        f"- Citation edges: {len(old_edges)} → {len(new_edges)} (added {len(new_edges - old_edges)}, removed {len(old_edges - new_edges)})",
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


def git_env() -> dict[str, str]:
    return {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


def git_failure(stderr: str, fallback: str) -> AtlasError:
    """One line from git, with no traceback."""
    lines = [line.strip() for line in (stderr or "").splitlines() if line.strip()]
    chosen = ""
    for line in lines:
        if line.lower().startswith(("fatal:", "error:")):
            chosen = line
            break
    if not chosen and lines:
        chosen = lines[-1]
    if len(chosen) > 300:
        chosen = chosen[:300]
    return AtlasError(chosen or fallback)


def run_git(args: list[str], cwd: Path | None, fallback: str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        args,
        cwd=cwd,
        env=git_env(),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise git_failure(result.stderr or result.stdout, fallback)
    return result


def assert_sha_is_ancestor(repo: Path, sha: str, head: str) -> None:
    """Fail unless sha is the commit named by head, or an ancestor of it.

    A missing object is not an ancestor. head is a revision already in repo.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise AtlasError(f"{sha} is not a commit sha")
    resolved = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{head}^{{commit}}"],
        cwd=repo,
        env=git_env(),
        capture_output=True,
        text=True,
    )
    head_sha = resolved.stdout.strip()
    if resolved.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", head_sha):
        raise AtlasError("could not read upstream HEAD")
    if sha == head_sha:
        return
    check = subprocess.run(
        ["git", "merge-base", "--is-ancestor", sha, head_sha],
        cwd=repo,
        env=git_env(),
        capture_output=True,
        text=True,
    )
    if check.returncode != 0:
        raise AtlasError(f"{sha} is not an ancestor of upstream HEAD")


def ensure_ancestor_of_origin_head(repo: Path, sha: str) -> None:
    """Fetch origin HEAD and require sha to be that commit or an ancestor.

    Uses `git fetch --filter=blob:none origin HEAD` and then
    `git merge-base --is-ancestor`. The repository must already have origin.
    """
    run_git(
        ["git", "fetch", "--filter=blob:none", "origin", "HEAD"],
        repo,
        "could not fetch upstream HEAD",
    )
    assert_sha_is_ancestor(repo, sha, "FETCH_HEAD")


def require_upstream_ancestor(url: str, sha: str) -> None:
    """Fail unless sha is HEAD of url or an ancestor of that HEAD."""
    with tempfile.TemporaryDirectory(prefix="atlas-ancestor-") as tmp:
        dest = Path(tmp) / "repo"
        run_git(
            ["git", "clone", "--filter=blob:none", "--no-checkout", url, str(dest)],
            None,
            "could not fetch upstream HEAD",
        )
        ensure_ancestor_of_origin_head(dest, sha)


def materialize_upstream(url: str, sha: str, dest: Path) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise AtlasError(f"{sha} is not a commit sha")
    if not (dest / ".git").exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        run_git(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--sparse",
                "--no-checkout",
                url,
                str(dest),
            ],
            None,
            "could not fetch upstream",
        )
    # Check ancestry before the depth-1 fetch, which replaces FETCH_HEAD and
    # can shallow the clone. A fork commit served by the same URL is not an ancestor.
    ensure_ancestor_of_origin_head(dest, sha)
    run_git(
        ["git", "fetch", "--filter=blob:none", "--depth", "1", "origin", sha],
        dest,
        "could not fetch upstream",
    )
    subprocess.run(
        ["git", "sparse-checkout", "init", "--no-cone"],
        cwd=dest,
        env=git_env(),
        check=False,
    )
    run_git(
        ["git", "sparse-checkout", "set", "--no-cone", *SPARSE_PATHS],
        dest,
        "could not fetch upstream",
    )
    run_git(["git", "checkout", "--detach", "FETCH_HEAD"], dest, "could not fetch upstream")
    got = run_git(["git", "rev-parse", "HEAD"], dest, "could not fetch upstream").stdout.strip()
    if got != sha:
        raise AtlasError(f"fetched {got}, expected {sha}")
