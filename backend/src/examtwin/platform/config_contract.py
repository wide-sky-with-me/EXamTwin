from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from examtwin.platform.config import PROJECT_ROOT, Settings

COMPOSE_ONLY_ENV_KEYS = frozenset(
    {
        "CONTAINER_PROXY_URL",
        "EXAMTWIN_STORAGE_ROOT",
        "LOCAL_GID",
        "LOCAL_UID",
        "PAPER_WORKER_REPLICAS",
        "POSTGRES_DB",
        "POSTGRES_PASSWORD",
        "POSTGRES_USER",
    }
)
OPTIONAL_NON_SETTINGS_ENV_KEYS = frozenset(
    {
        "VITE_API_BASE",
        "VITE_API_PROXY_TARGET",
    }
)


def seed_example_environment(project_root: Path = PROJECT_ROOT) -> None:
    """Populate a non-secret process with the complete documented config contract."""

    for name, value in dotenv_values(project_root / ".env.example").items():
        if value is not None:
            os.environ.setdefault(name, value)


@dataclass(frozen=True)
class EnvironmentContractAudit:
    expected_keys: frozenset[str]
    example_keys: frozenset[str]
    local_keys: frozenset[str] | None
    duplicate_example_keys: tuple[str, ...]
    duplicate_local_keys: tuple[str, ...]

    @property
    def errors(self) -> list[str]:
        messages: list[str] = []
        comparisons: list[tuple[str, frozenset[str]]] = [
            (".env.example missing", self.expected_keys - self.example_keys),
            (".env.example unknown", self.example_keys - self.expected_keys),
        ]
        if self.local_keys is not None:
            comparisons.extend(
                (
                    (".env missing", self.expected_keys - self.local_keys),
                    (".env unknown", self.local_keys - self.expected_keys),
                )
            )
        for label, keys in comparisons:
            if keys:
                messages.append(f"{label}: {', '.join(sorted(keys))}")
        if self.duplicate_example_keys:
            messages.append(f".env.example duplicate: {', '.join(self.duplicate_example_keys)}")
        if self.duplicate_local_keys:
            messages.append(f".env duplicate: {', '.join(self.duplicate_local_keys)}")
        return messages


def _environment_keys(path: Path) -> tuple[frozenset[str], tuple[str, ...]]:
    counts: dict[str, int] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if not key or not key.replace("_", "").isalnum() or not key[0].isalpha():
            continue
        counts[key] = counts.get(key, 0) + 1
    duplicates = tuple(sorted(key for key, count in counts.items() if count > 1))
    return frozenset(counts), duplicates


def audit_environment_contract(project_root: Path = PROJECT_ROOT) -> EnvironmentContractAudit:
    expected = frozenset(name.upper() for name in Settings.model_fields) | COMPOSE_ONLY_ENV_KEYS
    example, duplicate_example = _environment_keys(project_root / ".env.example")
    local_path = project_root / ".env"
    local, duplicate_local = _environment_keys(local_path) if local_path.is_file() else (None, ())
    return EnvironmentContractAudit(
        expected_keys=expected,
        example_keys=example - OPTIONAL_NON_SETTINGS_ENV_KEYS,
        local_keys=None if local is None else local - OPTIONAL_NON_SETTINGS_ENV_KEYS,
        duplicate_example_keys=duplicate_example,
        duplicate_local_keys=duplicate_local,
    )
