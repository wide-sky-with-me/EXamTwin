from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1] / "backend" / "src" / "examtwin"
FEATURES = frozenset({"subjects", "knowledge", "assessment"})
FEATURE_DEPENDENCIES = {
    "subjects": frozenset(),
    "knowledge": frozenset({"subjects"}),
    "assessment": frozenset({"subjects", "knowledge"}),
}
ALLOWED_TOP_LEVEL = frozenset({*FEATURES, "app", "platform", "contracts"})
LEGACY_TOP_LEVEL = frozenset(
    {
        "agent_harness",
        "api",
        "config",
        "config_contract",
        "local_storage",
        "observability",
        "persistence",
        "prompt_templates",
        "schemas",
        "services",
        "storage",
    }
)


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def module_parts(path: Path) -> tuple[str, ...]:
    return path.relative_to(PACKAGE_ROOT).with_suffix("").parts


def check_file(path: Path) -> list[str]:
    parts = module_parts(path)
    top_level = parts[0]
    imports = imported_modules(path)
    errors: list[str] = []

    if top_level != "__init__" and top_level not in ALLOWED_TOP_LEVEL:
        errors.append(f"module must live in an explicit architecture boundary: {top_level}")
    if top_level in LEGACY_TOP_LEVEL:
        errors.append(f"legacy horizontal module is forbidden: {top_level}")

    if top_level == "platform":
        for imported in imports:
            if imported == "examtwin.app" or imported.startswith("examtwin.app."):
                errors.append(f"platform must not depend on app: {imported}")
            if any(
                imported == f"examtwin.{feature}" or imported.startswith(f"examtwin.{feature}.")
                for feature in FEATURES
            ):
                errors.append(f"platform must not depend on feature: {imported}")

    if top_level == "contracts":
        for imported in imports:
            if imported.startswith("examtwin.") and not (
                imported == "examtwin.contracts" or imported.startswith("examtwin.contracts.")
            ):
                errors.append(f"contracts must not depend on runtime modules: {imported}")

    if top_level in FEATURES:
        for imported in imports:
            if imported == "examtwin.app" or imported.startswith("examtwin.app."):
                errors.append(f"feature must not depend on app: {imported}")
            for feature in FEATURES - FEATURE_DEPENDENCIES[top_level] - {top_level}:
                if imported == f"examtwin.{feature}" or imported.startswith(f"examtwin.{feature}."):
                    errors.append(
                        f"{top_level} must not depend on downstream feature {feature}: {imported}"
                    )
            for feature in FEATURE_DEPENDENCIES[top_level]:
                prefix = f"examtwin.{feature}"
                if (imported == prefix or imported.startswith(f"{prefix}.")) and imported != (
                    f"{prefix}.public"
                ):
                    errors.append(f"cross-feature imports must use {feature}.public: {imported}")

    if top_level != "app":
        for imported in imports:
            if imported == "fastapi" or imported.startswith("fastapi."):
                errors.append(f"FastAPI is restricted to the app boundary: {imported}")

    return [f"{path.relative_to(PACKAGE_ROOT.parent)}: {error}" for error in errors]


def main() -> int:
    errors = [
        error
        for path in sorted(PACKAGE_ROOT.rglob("*.py"))
        if "__pycache__" not in path.parts
        for error in check_file(path)
    ]
    if errors:
        print("Architecture dependency violations:")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("Architecture dependency rules passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
