"""Validate lever params against a lever's schema with reasons a technician can read."""

from __future__ import annotations

import re
from collections.abc import Mapping

from core.levers.models import ParamSpec

_PYTHON_TYPE = {"string": str, "integer": int, "boolean": bool}


def _type_name(value: object) -> str:
    return {str: "string", int: "integer", bool: "boolean", float: "number"}.get(type(value), type(value).__name__)


def _check_one(name: str, spec: ParamSpec, value: object) -> str | None:
    # bool is a subclass of int in Python, so compare exact types: True is not an integer here.
    if type(value) is not _PYTHON_TYPE[spec.type]:
        return f"param '{name}': expected {spec.type}, got {_type_name(value)}"
    if spec.enum is not None and value not in spec.enum:
        allowed = ", ".join(repr(v) for v in spec.enum)
        return f"param '{name}': {value!r} is not one of {allowed}"
    if isinstance(value, str):
        if spec.max_length is not None and len(value) > spec.max_length:
            return f"param '{name}': length {len(value)} exceeds max length {spec.max_length}"
        if spec.pattern is not None and re.fullmatch(spec.pattern, value) is None:
            return f"param '{name}': does not match the required format {spec.pattern}"
    if isinstance(value, int) and not isinstance(value, bool):
        if spec.minimum is not None and value < spec.minimum:
            return f"param '{name}': {value} is below the minimum {spec.minimum}"
        if spec.maximum is not None and value > spec.maximum:
            return f"param '{name}': {value} is above the maximum {spec.maximum}"
    return None


def validate_params(schema: Mapping[str, ParamSpec], params: object) -> list[str]:
    """Return every problem found; an empty list means the params are valid."""
    if not isinstance(params, Mapping):
        return [f"params must be an object, got {_type_name(params)}"]
    errors: list[str] = []
    for name, spec in schema.items():
        if name not in params:
            if spec.required:
                errors.append(f"param '{name}': required but missing")
            continue
        problem = _check_one(name, spec, params[name])
        if problem:
            errors.append(problem)
    errors.extend(f"param '{name}': not in the lever's schema" for name in params if name not in schema)
    return errors
