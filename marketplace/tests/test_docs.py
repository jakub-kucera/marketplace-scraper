"""Structural checks on docs/ — the guard against the drift that motivated the reorg.

Docs went stale because status was asserted in four places that nothing reconciled.
The fix is structural: `status` lives in one place (each doc's front-matter), and
these tests fail when the index, the links, or a code comment disagree with it.

No database, no network — pure filesystem, so this runs in any CI job.
"""
import re
from datetime import date
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DOCS = REPO / "docs"
INDEX = DOCS / "README.md"

#: The complete `status:` vocabulary. Adding a sixth value is a deliberate decision —
#: change it here and in docs/README.md's "How these docs work" table together.
STATUSES = {"active", "proposal", "reference", "shipped", "superseded"}
#: status -> field that must accompany it
REQUIRED_WITH = {"shipped": "shipped_in", "superseded": "superseded_by"}

MD_LINK = re.compile(r"\]\((?!https?:|mailto:|#)([^)\s]+?)(?:#[^)\s]*)?\)")
INDEX_ROW = re.compile(r"^\| \[`[^`]+`\]\(([^)]+)\)", re.M)
#: docs/... paths named from source, e.g. `# see docs/research/PRICE_PARSING.md §6`
CODE_DOC_REF = re.compile(r"docs/[A-Za-z0-9_/.-]+\.md")
#: stripped before CODE_DOC_REF runs — a docs path inside a URL belongs to that host, not us
URL_REF = re.compile(r"\b\w+://\S+")

SOURCE_GLOBS = ("*.py", "*.toml", "*.yml", "*.yaml")
#: `.claude` mirrors pytest.ini's norecursedirs — it holds agent-created worktrees, full
#: checkouts of other branches whose stale doc references are not this branch's problem.
SOURCE_SKIP = {".git", ".venv", "node_modules", "__pycache__", ".claude",
               "bazos_app_decomplied", "old_tests", "experiments"}
#: a separate git repo (own history, own remote) checked out here and gitignored — not part
#: of this repo's tree, so it carries none of this file's conventions and is never "missing".
EXTERNAL_DOCS_DIR = "docs/internal/"


def all_docs():
    return sorted(p for p in DOCS.rglob("*.md") if "internal" not in p.relative_to(DOCS).parts)


def front_matter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    block = text.split("---\n", 2)[1]
    return dict(
        (k.strip(), v.strip().strip('"'))
        for k, _, v in (line.partition(": ") for line in block.splitlines())
        if k.strip() and v
    )


def source_files():
    for pattern in SOURCE_GLOBS:
        for path in REPO.rglob(pattern):
            if not SOURCE_SKIP.intersection(path.parts):
                yield path


def rel(path: Path) -> str:
    return str(path.relative_to(REPO))


@pytest.mark.parametrize("doc", all_docs(), ids=rel)
def test_every_doc_has_valid_front_matter(doc):
    """title/status/updated are mandatory, and status comes from the fixed vocabulary."""
    fm = front_matter(doc)
    assert fm, f"{rel(doc)} has no YAML front-matter — see docs/README.md"

    missing = {"title", "status", "updated"} - fm.keys()
    assert not missing, f"{rel(doc)} front-matter is missing {sorted(missing)}"

    assert fm["status"] in STATUSES, (
        f"{rel(doc)} has status={fm['status']!r}; allowed: {sorted(STATUSES)}"
    )

    required = REQUIRED_WITH.get(fm["status"])
    assert required is None or required in fm, (
        f"{rel(doc)} is status={fm['status']} so it must also carry `{required}:`"
    )

    for field in ("updated", "verified"):
        if field in fm:
            date.fromisoformat(fm[field])  # raises on a malformed date


@pytest.mark.parametrize("doc", all_docs(), ids=rel)
def test_front_matter_title_matches_the_h1(doc):
    """One title, not two that can drift apart."""
    fm = front_matter(doc)
    h1 = re.search(r"^# (.+)$", doc.read_text(encoding="utf-8"), re.M)
    assert h1, f"{rel(doc)} has no H1"
    assert fm.get("title") == h1.group(1).strip(), (
        f"{rel(doc)}: front-matter title {fm.get('title')!r} != H1 {h1.group(1).strip()!r}"
    )


def test_superseded_docs_point_at_something_that_exists():
    for doc in all_docs():
        fm = front_matter(doc)
        if fm.get("status") == "superseded":
            target = REPO / fm["superseded_by"]
            assert target.exists(), (
                f"{rel(doc)} is superseded_by {fm['superseded_by']}, which does not exist"
            )


def test_archive_subdirectory_matches_the_status_it_holds():
    """docs/archive/<status>/ is named for the status of what's in it."""
    for doc in (DOCS / "archive").rglob("*.md"):
        expected = doc.relative_to(DOCS / "archive").parts[0]
        actual = front_matter(doc).get("status")
        assert actual == expected, (
            f"{rel(doc)} sits in archive/{expected}/ but is status={actual}"
        )


def test_no_broken_relative_links_between_docs():
    broken = []
    for doc in all_docs():
        for match in MD_LINK.finditer(doc.read_text(encoding="utf-8")):
            if not (doc.parent / match.group(1)).resolve().exists():
                broken.append(f"{rel(doc)} -> {match.group(1)}")
    assert not broken, "broken relative links:\n  " + "\n  ".join(broken)


def test_link_labels_name_the_file_they_point_at():
    """A label of `FOO.md` pointing at BAR.md is how a rename half-lands."""
    labelled = re.compile(r"\[`([^`]*?\.md)`\]\((?!https?:)([^)\s]+?\.md)")
    mismatched = []
    for doc in all_docs():
        for match in labelled.finditer(doc.read_text(encoding="utf-8")):
            if Path(match.group(1)).name != Path(match.group(2)).name:
                mismatched.append(f"{rel(doc)}: `{match.group(1)}` -> {match.group(2)}")
    assert not mismatched, "link labels disagree with their targets:\n  " + "\n  ".join(mismatched)


def test_index_lists_every_doc_exactly_once():
    listed = [(INDEX.parent / m).resolve() for m in INDEX_ROW.findall(INDEX.read_text(encoding="utf-8"))]
    expected = {d.resolve() for d in all_docs()} - {INDEX.resolve()}

    orphans = sorted(rel(p) for p in expected - set(listed))
    assert not orphans, f"not listed in docs/README.md: {orphans}"

    phantoms = sorted(rel(p) for p in set(listed) - expected)
    assert not phantoms, f"listed in docs/README.md but not a doc: {phantoms}"

    dupes = sorted({rel(p) for p in listed if listed.count(p) > 1})
    assert not dupes, f"listed in docs/README.md more than once: {dupes}"


def test_index_status_matches_front_matter():
    """The index repeats each status; this is what stops the two from drifting."""
    badge_for = {"active": "active", "proposal": "proposal", "reference": "reference",
                 "shipped": "shipped", "superseded": "superseded"}
    row = re.compile(r"^\| \[`[^`]+`\]\(([^)]+)\) \| [^\w|]*(\w+)", re.M)
    wrong = []
    for target, badge in row.findall(INDEX.read_text(encoding="utf-8")):
        doc = (INDEX.parent / target).resolve()
        actual = front_matter(doc).get("status")
        if badge_for.get(actual) != badge:
            wrong.append(f"{target}: index says {badge!r}, front-matter says {actual!r}")
    assert not wrong, "docs/README.md disagrees with front-matter:\n  " + "\n  ".join(wrong)


def test_doc_paths_named_from_source_exist():
    """A moved doc must not leave a dangling path in a code comment.

    This is the check that would have caught the STAGE9_SBAZAR_SPEC reference that
    sat in four source files while the file it named had never existed.
    """
    missing = []
    for src in source_files():
        try:
            text = src.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        text = URL_REF.sub(" ", text)
        for ref in CODE_DOC_REF.findall(text):
            if ref.startswith(EXTERNAL_DOCS_DIR):
                continue
            if not (REPO / ref).exists():
                missing.append(f"{rel(src)} -> {ref}")
    assert not missing, "source files name docs that do not exist:\n  " + "\n  ".join(missing)
