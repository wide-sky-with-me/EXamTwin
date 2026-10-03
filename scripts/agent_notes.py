"""Verify and archive Agent Notes under .agents/notes.

Rules follow write-notes-like-deepseek (.agents/skills/write-notes-like-deepseek):
path is identity ({lifecycle}/{class}/yyyy-mm-dd-topic.md), the header block and
required sections are checked per lifecycle, and archived notes are sealed in
archived/manifest.json by SHA-256 and may only ever be added.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
NOTES_ROOT = PROJECT_ROOT / ".agents" / "notes"

LIFECYCLES = ("proposed", "implemented", "rejected")
ARCHIVE = "archived"
CLASSES = ("feature", "bug-fix", "simplification", "architecture", "process", "testing")
ROOT_FILES = frozenset({"AGENTS.md"})
MANIFEST = "manifest.json"
FILENAME = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*\.md$")
TITLE = re.compile(r"^# Agent Note[:：] \S")
STATUS = re.compile(r"^Status: (?P<status>proposed|implemented|rejected)(?P<rest>.*)$")
ARCHIVED_LINE = re.compile(r"^Archived: \d{4}-\d{2}-\d{2}$")
MARKDOWN_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")

PROBLEM = ("## Problem", "## 问题")
REQUIRED_SECTIONS = {
    "proposed": (
        ("## Proposal", "## 提议", "## 方案", "## 提案"),
        ("## Acceptance criteria", "## 验收标准", "## 验收条件", "## 接受标准"),
        ("## Risks", "## 风险"),
    ),
    "implemented": (
        ("## Decision", "## 决定", "## 决策"),
        ("## Consequences", "## 后果", "## 影响", "## 结果", "## 结果与代价", "## 影响与验证"),
    ),
    "rejected": (("## Proposal", "## 提议", "## 方案", "## 提案"),),
}
PROPOSAL_HEADINGS = frozenset(
    {
        "## Proposal",
        "## Plan",
        "## Migration plan",
        "## Acceptance criteria",
        "## 提议",
        "## 方案",
        "## 提案",
        "## 计划",
        "## 规划",
        "## 迁移计划",
        "## 验收标准",
        "## 验收条件",
        "## 接受标准",
    }
)
ALTERNATIVES = re.compile(r"^## (?:Alternatives considered|.{0,8}?(?:替代方案|备选(?:方案)?))$")


@dataclass(frozen=True)
class Note:
    lifecycle: str
    path: Path


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def walk_tree(root: Path) -> tuple[list[Note], list[str]]:
    """Return active notes and structural errors; archived/ is checked separately."""
    notes: list[Note] = []
    errors: list[str] = []
    if not root.is_dir():
        return notes, errors
    for index in root.rglob("INDEX.md"):
        errors.append(f"{_relative(index, root)}: centralized INDEX.md is forbidden")
    for entry in sorted(root.iterdir()):
        if entry.is_file():
            if entry.name not in ROOT_FILES:
                errors.append(f"{entry.name}: only AGENTS.md may sit at the notes root")
            continue
        if entry.name not in (*LIFECYCLES, ARCHIVE):
            errors.append(
                f"{entry.name}/: unknown lifecycle folder "
                f"(allowed: {', '.join(LIFECYCLES)}, {ARCHIVE})"
            )
    for lifecycle in LIFECYCLES:
        base = root / lifecycle
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_dir() or path.name == "INDEX.md":
                continue
            relative = path.relative_to(base).parts
            label = _relative(path, root)
            if len(relative) != 2:
                errors.append(f"{label}: expected {lifecycle}/<class>/yyyy-mm-dd-topic.md")
                continue
            if relative[0] not in CLASSES:
                errors.append(
                    f"{label}: unknown class {relative[0]!r} (allowed: {', '.join(CLASSES)})"
                )
                continue
            if not FILENAME.match(path.name):
                errors.append(
                    f"{label}: filename must be yyyy-mm-dd-topic.md in lowercase kebab-case"
                )
                continue
            notes.append(Note(lifecycle, path))
    return notes, errors


def _link_errors(path: Path, text: str, root: Path) -> list[str]:
    errors: list[str] = []
    for target in MARKDOWN_LINK.findall(text):
        if re.match(r"^[a-z][a-z0-9+.-]*:", target) or target.startswith("#"):
            continue
        resolved = (path.parent / target.split("#", 1)[0]).resolve()
        if not resolved.exists():
            errors.append(f"{_relative(path, root)}: broken relative link {target}")
    return errors


def check_format(note: Note, root: Path) -> list[str]:
    label = _relative(note.path, root)
    text = note.path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    lines = text.split("\n")
    errors: list[str] = []
    if len(lines) < 5 or not TITLE.match(lines[0]):
        return [f"{label}: line 1 must be '# Agent Note: <title>'"]
    if lines[1] != "" or lines[3] != "":
        errors.append(f"{label}: lines 2 and 4 must be blank")
    status = STATUS.match(lines[2])
    if status is None:
        errors.append(f"{label}: line 3 must be 'Status: <lifecycle>'")
    elif status["status"] != note.lifecycle:
        errors.append(
            f"{label}: Status {status['status']!r} does not match folder {note.lifecycle!r}"
        )
    elif note.lifecycle == "rejected" and not re.match(r"^ — \S", status["rest"]):
        errors.append(f"{label}: rejected notes need 'Status: rejected — <reason>'")
    elif note.lifecycle != "rejected" and status["rest"]:
        errors.append(f"{label}: Status line must not carry extra text")
    if sum(1 for line in lines if line.startswith("Status:")) != 1:
        errors.append(f"{label}: exactly one Status line is allowed")

    in_fence = False
    headings: list[str] = []
    for line in lines:
        if line.startswith("```"):
            in_fence = not in_fence
        elif not in_fence and line.startswith("## "):
            headings.append(re.sub(r"[（(].*[）)]\s*$", "", line).rstrip())
    if not headings or headings[0] not in PROBLEM:
        errors.append(f"{label}: first section must be ## Problem")
    for aliases in REQUIRED_SECTIONS[note.lifecycle]:
        if not any(heading in aliases for heading in headings):
            errors.append(f"{label}: missing {aliases[0]}")
    if not any(ALTERNATIVES.match(heading) for heading in headings):
        errors.append(f"{label}: missing ## Alternatives considered")
    if note.lifecycle == "implemented":
        for heading in headings:
            if heading in PROPOSAL_HEADINGS:
                errors.append(
                    f"{label}: implemented notes must not keep proposal heading {heading!r}"
                )
    errors.extend(_link_errors(note.path, text, root))
    return errors


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_manifest(root: Path) -> dict[str, str]:
    manifest = root / ARCHIVE / MANIFEST
    if not manifest.is_file():
        return {}
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    return {str(key): str(value) for key, value in payload.items()}


def _write_manifest(root: Path, seals: dict[str, str]) -> None:
    manifest = root / ARCHIVE / MANIFEST
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text(json.dumps(dict(sorted(seals.items())), indent=2) + "\n", encoding="utf-8")


def _archived_files(root: Path) -> list[Path]:
    base = root / ARCHIVE
    if not base.is_dir():
        return []
    return sorted(path for path in base.rglob("*.md"))


def _baseline_manifest(root: Path) -> dict[str, str] | None:
    ref = os.environ.get("AGENT_NOTE_ARCHIVE_BASE_REF", "HEAD")
    manifest = (root / ARCHIVE / MANIFEST).relative_to(PROJECT_ROOT).as_posix()
    try:
        result = subprocess.run(
            ["git", "show", f"{ref}:{manifest}"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return (
            {}
            if "exists on disk, but not in" in result.stderr or "does not exist" in result.stderr
            else None
        )
    return {str(key): str(value) for key, value in json.loads(result.stdout).items()}


def check_archive(root: Path, *, compare_baseline: bool = True) -> list[str]:
    errors: list[str] = []
    seals = _load_manifest(root)
    archived = {path.relative_to(root / ARCHIVE).as_posix(): path for path in _archived_files(root)}
    for relative, path in archived.items():
        lines = path.read_text(encoding="utf-8").split("\n")
        if (
            len(lines) < 6
            or not TITLE.match(lines[0])
            or lines[2] != "Status: implemented"
            or not ARCHIVED_LINE.match(lines[3])
            or lines[4] != ""
        ):
            errors.append(
                f"archived/{relative}: header must be title, blank, "
                "'Status: implemented', 'Archived: YYYY-MM-DD', blank"
            )
        if relative not in seals:
            errors.append(f"archived/{relative}: missing seal in {MANIFEST}")
        elif seals[relative] != _sha256(path):
            errors.append(f"archived/{relative}: content changed after archiving")
    for relative in seals:
        if relative not in archived:
            errors.append(f"archived/{relative}: sealed note is missing")
    if compare_baseline:
        baseline = _baseline_manifest(root)
        if baseline is None:
            print(
                "agent-notes: git baseline unavailable; checked seals against disk only",
                file=sys.stderr,
            )
        else:
            for relative, digest in baseline.items():
                if seals.get(relative) != digest:
                    errors.append(f"archived/{relative}: sealed entry was changed or removed")
    return errors


def check(root: Path = NOTES_ROOT) -> list[str]:
    notes, errors = walk_tree(root)
    for note in notes:
        errors.extend(check_format(note, root))
    errors.extend(check_archive(root))
    return errors


def archive(note_path: Path, superseded_by: Path | None, root: Path = NOTES_ROOT) -> list[str]:
    note_path = note_path.resolve()
    implemented = (root / "implemented").resolve()
    if not note_path.is_relative_to(implemented) or not note_path.is_file():
        raise SystemExit(f"only existing implemented notes can be archived: {note_path}")
    if superseded_by is not None and not superseded_by.resolve().is_file():
        raise SystemExit(f"superseding note does not exist: {superseded_by}")
    if errors := check_archive(root, compare_baseline=False):
        raise SystemExit("archive seals are already broken:\n" + "\n".join(errors))
    lines = note_path.read_text(encoding="utf-8").split("\n")
    if len(lines) < 4 or lines[2] != "Status: implemented":
        raise SystemExit(f"{note_path}: line 3 must be 'Status: implemented'")
    lines.insert(3, f"Archived: {date.today().isoformat()}")
    relative = note_path.relative_to(implemented)
    target = root / ARCHIVE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines), encoding="utf-8")
    note_path.unlink()
    seals = _load_manifest(root)
    seals[relative.as_posix()] = _sha256(target)
    _write_manifest(root, seals)

    if superseded_by is not None:
        successor = superseded_by.resolve()
        link = os.path.relpath(target, successor.parent)
        text = successor.read_text(encoding="utf-8").rstrip("\n")
        successor.write_text(f"{text}\n\n取代：[{relative.stem}]({link})\n", encoding="utf-8")

    inbound: list[str] = []
    notes, _ = walk_tree(root)
    for note in notes:
        for target_link in MARKDOWN_LINK.findall(note.path.read_text(encoding="utf-8")):
            if (note.path.parent / target_link.split("#", 1)[0]).resolve() == note_path:
                inbound.append(f"{_relative(note.path, root)} -> {target_link}")
    return inbound


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("check", help="verify tree, format and archive seals (default)")
    archive_parser = commands.add_parser(
        "archive", help="move an implemented note to archived/ and seal it"
    )
    archive_parser.add_argument("note", type=Path)
    archive_parser.add_argument("--superseded-by", type=Path)
    args = parser.parse_args(argv)

    if args.command == "archive":
        inbound = archive(args.note, args.superseded_by)
        print(f"archived {args.note}")
        for line in inbound:
            print(f"inbound link to fix: {line}")
        return 1 if inbound else 0

    errors = check()
    for error in errors:
        print(error)
    if errors:
        return 1
    print("Agent notes passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
