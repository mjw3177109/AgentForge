from __future__ import annotations
from pathlib import Path
from typing import Any
import json
from jsonschema import Draft202012Validator, FormatChecker
from agentforge.errors import ProtocolError


class ProtocolValidator:
    def __init__(self, schema_root: Path | None = None):
        self.schema_root = schema_root or (Path(__file__).resolve().parents[3] / "protocol_bundle" / "schemas")

    def validate(self, data: dict[str, Any], schema_name: str) -> None:
        schema_path = self.schema_root / schema_name
        if not schema_path.is_file():
            raise ProtocolError(f"Schema not found: {schema_path}")
        schema = json.loads(schema_path.read_text("utf-8"))
        errors = sorted(
            Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(data),
            key=lambda error: list(error.path),
        )
        if errors:
            details = []
            for error in errors:
                where = "/".join(str(item) for item in error.absolute_path) or "<root>"
                details.append(f"{where}: {error.message}")
            raise ProtocolError("; ".join(details))
