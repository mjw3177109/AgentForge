from pathlib import Path
import json
from jsonschema import Draft202012Validator
from agentforge.errors import ProtocolError

class ProtocolValidator:
    def __init__(self, schema_root: Path):
        self.schema_root = schema_root

    def validate(self, data, schema_name: str) -> None:
        schema_path = self.schema_root / schema_name
        schema = json.loads(schema_path.read_text("utf-8"))
        errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: list(e.path))
        if errors:
            raise ProtocolError("; ".join(e.message for e in errors))
