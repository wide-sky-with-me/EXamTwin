from __future__ import annotations

import argparse
import json
from pathlib import Path

from examtwin.main import app


def rendered_schema() -> str:
    return json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Export ExamTwin's deterministic OpenAPI schema")
    parser.add_argument("output", type=Path)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    expected = rendered_schema()
    if arguments.check:
        if not arguments.output.is_file() or arguments.output.read_text("utf-8") != expected:
            parser.error(f"OpenAPI snapshot is stale: {arguments.output}")
        return 0
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = arguments.output.with_name(f".{arguments.output.name}.tmp")
    temporary.write_text(expected, encoding="utf-8")
    temporary.replace(arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
