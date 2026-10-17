from pathlib import Path
import json
import yaml
from jsonschema import validate

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
EX = ROOT / "example_project" / ".agent"

checks = [
    (EX / "project.yaml", ROOT / "schemas/project.schema.json"),
    (EX / "requirements/REQ-000102.yaml", ROOT / "schemas/requirement.schema.json"),
    (EX / "decisions/ADR-000026.yaml", ROOT / "schemas/adr.schema.json"),
    (EX / "tasks/TASK-000313.yaml", ROOT / "schemas/task.schema.json"),
]

root_project = REPO / ".agent" / "project.yaml"
if root_project.is_file():
    checks.append((root_project, ROOT / "schemas/project.schema.json"))

for data_path, schema_path in checks:
    data = yaml.safe_load(data_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    validate(data, schema)
    print(f"[PASS] {data_path.relative_to(REPO)}")

print("All protocol examples and project protocol are valid.")
