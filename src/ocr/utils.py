"""VLM output parsing utilities.

Handles the messy reality of LLM JSON output: markdown fences,
trailing commas, partial JSON, etc. Validates against Pydantic schemas.
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, ValidationError


class VlmParseError(Exception):
    """Raised when VLM output cannot be parsed into the expected schema."""

    def __init__(self, message: str, raw_output: str) -> None:
        super().__init__(message)
        self.raw_output = raw_output


def parse_vlm_json[T: BaseModel](raw: str, schema: type[T]) -> T:
    """Parse VLM text output into a Pydantic model.

    Handles common VLM output quirks:
        - Markdown code fences (```json ... ```)
        - Trailing commas before closing braces/brackets
        - Leading/trailing whitespace

    Args:
        raw: Raw text output from the VLM.
        schema: Pydantic model class to validate against.

    Returns:
        Validated Pydantic model instance.

    Raises:
        VlmParseError: If JSON parsing or Pydantic validation fails.
    """
    cleaned = _strip_markdown_fences(raw.strip())
    cleaned = _fix_trailing_commas(cleaned)

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise VlmParseError(
            f"Invalid JSON from VLM: {exc}",
            raw_output=raw,
        ) from exc

    try:
        return schema.model_validate(data)
    except ValidationError as exc:
        raise VlmParseError(
            f"Schema validation failed: {exc}",
            raw_output=raw,
        ) from exc


def _strip_markdown_fences(text: str) -> str:
    """Remove markdown code fences wrapping JSON."""
    # Match ```json ... ``` or ``` ... ```
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        return match.group(1).strip()
    return text


def _fix_trailing_commas(text: str) -> str:
    """Remove trailing commas before } or ]."""
    return re.sub(r",\s*([}\]])", r"\1", text)
