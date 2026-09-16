"""Versioned prompt files: `llm/prompts/<name>/v<N>.md`.

Same discipline as `bazos/pricing/artifacts/<name>/<version>/manifest.json`, for the same
reason — the text is an input that changes the output, so a result that cannot name the
text that produced it is unattributable. **Editing a shipped prompt in place is a bug;
adding `v2` is the change.** The resolved version is written to every `LLMCall` row.

File format is optional YAML-ish front matter (only `system:` is read) followed by the
user-message template. Substitution is `$name` / `${name}` rather than `str.format`,
because these templates are full of JSON examples and `{"index": 0}` would otherwise need
escaping in every one of them.
"""
import re
from dataclasses import dataclass
from pathlib import Path
from string import Template

PROMPTS_DIR = Path(__file__).resolve().parent

_VERSION_FILE = re.compile(r"^v(\d+)\.md$")
_FRONT_MATTER = re.compile(r"\A---\n(.*?)\n---\n?", re.S)


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    system: str | None
    template: str

    def render(self, **variables: object) -> str:
        """Substitute `$name` placeholders. A missing variable raises rather than
        shipping a prompt containing a literal `$title`."""
        return Template(self.template).substitute(**variables)


def _parse(text: str) -> tuple[str | None, str]:
    match = _FRONT_MATTER.match(text)
    if not match:
        return None, text.strip()
    system = None
    for line in match.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "system":
            system = value.strip().strip('"')
    return system, text[match.end():].strip()


def load(name: str, version: str = "latest", base: Path | None = None) -> Prompt:
    """Load a prompt by name and version (`"v2"`, `"2"`, or `"latest"`)."""
    directory = (base or PROMPTS_DIR) / name
    if not directory.is_dir():
        raise FileNotFoundError(f"No prompt directory for {name!r} at {directory}")

    if version == "latest":
        # Numeric max, not a string sort: v10 must beat v9.
        numbers = [
            int(m.group(1))
            for path in directory.iterdir()
            if (m := _VERSION_FILE.match(path.name))
        ]
        if not numbers:
            raise FileNotFoundError(f"No v<N>.md files in {directory}")
        version = f"v{max(numbers)}"
    elif not version.startswith("v"):
        version = f"v{version}"

    path = directory / f"{version}.md"
    if not path.is_file():
        raise FileNotFoundError(f"No prompt {name!r} version {version!r} at {path}")

    system, template = _parse(path.read_text(encoding="utf-8"))
    return Prompt(name=name, version=version, system=system, template=template)
