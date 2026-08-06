from __future__ import annotations

from functools import lru_cache
from importlib.resources import files


@lru_cache(maxsize=16)
def load_prompt_template(name: str) -> str:
    """Load a trusted, packaged prompt template by its repository-relative name."""
    normalized = name.strip().replace("\\", "/")
    if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
        raise ValueError("prompt template name must stay inside the packaged prompt directory")
    template = files("examtwin.platform").joinpath("prompt_templates", *normalized.split("/"))
    text = template.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"prompt template is empty: {normalized}")
    return text
