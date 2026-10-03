"""Enforce documentation budgets, present-tense wording and relative links.

Budgets live in docs/doc-budgets.json and count CJK characters plus Latin words.
Every Markdown file under docs/ and every AGENTS.md must have a budget; an
over-budget file is moved down into a narrower document or condensed, never
granted silent headroom.
"""

from __future__ import annotations

import fnmatch
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUDGETS = PROJECT_ROOT / "docs" / "doc-budgets.json"
SKIPPED_DIRS = frozenset(
    {
        ".git",
        ".venv",
        ".uv-cache",
        "node_modules",
        "data",
        "var",
        "demo-jev",
        ".pytest_cache",
        ".ruff_cache",
    }
)
CJK = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
LATIN_WORD = re.compile(r"[A-Za-z0-9_]+(?:[-'][A-Za-z0-9_]+)*")
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
# History lives in git and .agents/notes; current-state documents describe what is true now.
HISTORY_WORDS = re.compile(
    r"以前|(?<![出实体表发])现在(?!时)|不再|改名为|曾经|原先|此前"
    r"|no longer|used to|previously|renamed to",
    re.IGNORECASE,
)
HISTORY_EXEMPT = ("docs/postmortem/",)


def count_units(text: str) -> int:
    return len(CJK.findall(text)) + len(LATIN_WORD.findall(CJK.sub(" ", text)))


def governed_files(root: Path = PROJECT_ROOT) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*.md"):
        parts = path.relative_to(root).parts
        if any(part in SKIPPED_DIRS for part in parts):
            continue
        if parts[0] == "docs" or path.name == "AGENTS.md" or parts == ("README.md",):
            files.append(path)
    return sorted(files)


def _prose_lines(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    in_fence = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence:
            lines.append((number, re.sub(r"`[^`]*`", "", line)))
    return lines


def budget_for(relative: str, budgets: dict[str, object]) -> int | None:
    files = budgets.get("files", {})
    if isinstance(files, dict) and relative in files:
        return int(files[relative])
    globs = budgets.get("globs", {})
    if isinstance(globs, dict):
        for pattern, limit in globs.items():
            if fnmatch.fnmatch(relative, pattern):
                return int(limit)
    return None


def check_file(path: Path, budgets: dict[str, object], root: Path = PROJECT_ROOT) -> list[str]:
    relative = path.relative_to(root).as_posix()
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    limit = budget_for(relative, budgets)
    if limit is None:
        errors.append(f"{relative}: no budget in docs/doc-budgets.json")
    elif (units := count_units(text)) > limit:
        errors.append(
            f"{relative}: {units} units exceeds budget {limit}; move detail down or condense"
        )
    for number, line in _prose_lines(text):
        if not relative.startswith(HISTORY_EXEMPT) and (match := HISTORY_WORDS.search(line)):
            errors.append(
                f"{relative}:{number}: history wording {match.group(0)!r}; "
                "describe the current state"
            )
        for target in MARKDOWN_LINK.findall(line):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
                continue
            if not (path.parent / target.split("#", 1)[0]).exists():
                errors.append(f"{relative}:{number}: broken relative link {target}")
    return errors


def check(root: Path = PROJECT_ROOT, budgets_path: Path = BUDGETS) -> list[str]:
    budgets = json.loads(budgets_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for path in governed_files(root):
        errors.extend(check_file(path, budgets, root))
    return errors


def main() -> int:
    errors = check()
    for error in errors:
        print(error)
    if errors:
        return 1
    print("Documentation budgets passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
