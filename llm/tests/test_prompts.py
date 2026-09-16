"""Versioned prompt files.

Prompts are files under `llm/prompts/<name>/v<N>.md` rather than inline f-strings for the
same reason `bazos/pricing/artifacts/<name>/<version>/` is a directory: editing the text
changes the output, so a result that cannot name the text that produced it is
unattributable. Editing a shipped prompt in place is a bug; adding v2 is the change.

Substitution is `$name`, not `str.format`, because these templates are full of JSON
examples and `{"index": 0}` would otherwise have to be escaped in every one of them.
"""
import pytest

from llm.prompts import Prompt, load


@pytest.fixture()
def prompt_dir(tmp_path):
    def write(name, version, text):
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        (d / f"v{version}.md").write_text(text, encoding="utf-8")
    return tmp_path, write


# ---------------------------------------------------------------------------
# loading
# ---------------------------------------------------------------------------

def test_loads_a_prompt_by_explicit_version(prompt_dir):
    base, write = prompt_dir
    write("adjudicate", 1, "pick one: $candidates")
    p = load("adjudicate", "v1", base=base)
    assert (p.name, p.version) == ("adjudicate", "v1")


def test_accepts_a_bare_version_number(prompt_dir):
    base, write = prompt_dir
    write("adjudicate", 1, "body")
    assert load("adjudicate", "1", base=base).version == "v1"


def test_latest_picks_the_highest_version_numerically(prompt_dir):
    """v10 must beat v9 — a string sort would get this backwards."""
    base, write = prompt_dir
    for v in (1, 2, 9, 10):
        write("adjudicate", v, f"body {v}")
    assert load("adjudicate", "latest", base=base).version == "v10"


def test_latest_is_the_default(prompt_dir):
    base, write = prompt_dir
    write("adjudicate", 3, "body")
    assert load("adjudicate", base=base).version == "v3"


def test_unknown_prompt_raises(prompt_dir):
    base, _ = prompt_dir
    with pytest.raises(FileNotFoundError, match="nosuch"):
        load("nosuch", base=base)


def test_unknown_version_raises(prompt_dir):
    base, write = prompt_dir
    write("adjudicate", 1, "body")
    with pytest.raises(FileNotFoundError, match="v7"):
        load("adjudicate", "v7", base=base)


# ---------------------------------------------------------------------------
# front matter
# ---------------------------------------------------------------------------

def test_front_matter_supplies_the_system_prompt(prompt_dir):
    base, write = prompt_dir
    write("adjudicate", 1, "---\nsystem: You match products.\n---\nBody here")
    p = load("adjudicate", base=base)
    assert p.system == "You match products."
    assert p.template == "Body here"


def test_a_prompt_without_front_matter_has_no_system(prompt_dir):
    base, write = prompt_dir
    write("adjudicate", 1, "Just the body")
    p = load("adjudicate", base=base)
    assert p.system is None
    assert p.template == "Just the body"


# ---------------------------------------------------------------------------
# rendering
# ---------------------------------------------------------------------------

def test_render_substitutes_named_variables(prompt_dir):
    base, write = prompt_dir
    write("adjudicate", 1, "Ad: $title\nCandidates: $candidates")
    rendered = load("adjudicate", base=base).render(title="Makita", candidates="a, b")
    assert rendered == "Ad: Makita\nCandidates: a, b"


def test_render_leaves_json_braces_alone(prompt_dir):
    """The reason substitution is $-style: every real prompt here contains a JSON example."""
    base, write = prompt_dir
    write("adjudicate", 1, 'Answer as {"index": 0, "reason": "..."} for $title')
    rendered = load("adjudicate", base=base).render(title="X")
    assert rendered == 'Answer as {"index": 0, "reason": "..."} for X'


def test_render_raises_on_a_missing_variable(prompt_dir):
    """Silently shipping a prompt containing a literal `$title` would be worse."""
    base, write = prompt_dir
    write("adjudicate", 1, "Ad: $title")
    with pytest.raises(KeyError, match="title"):
        load("adjudicate", base=base).render()


def test_prompt_is_frozen(prompt_dir):
    base, write = prompt_dir
    write("adjudicate", 1, "body")
    with pytest.raises(Exception):
        load("adjudicate", base=base).version = "v2"  # type: ignore[misc]


def test_is_a_prompt_instance(prompt_dir):
    base, write = prompt_dir
    write("adjudicate", 1, "body")
    assert isinstance(load("adjudicate", base=base), Prompt)
