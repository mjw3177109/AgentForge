from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MINIAPP = ROOT / "miniapp"

app_json = MINIAPP / "app.json"
if not app_json.is_file():
    raise SystemExit("miniapp/app.json is missing")

try:
    config = json.loads(app_json.read_text(encoding="utf-8"))
except json.JSONDecodeError as exc:
    raise SystemExit(f"miniapp/app.json is invalid JSON: {exc}") from exc

pages = config.get("pages")
if not isinstance(pages, list) or not pages:
    raise SystemExit("miniapp/app.json must declare at least one page")

required_root = [MINIAPP / "app.js", MINIAPP / "app.json"]
missing = [str(p.relative_to(ROOT)) for p in required_root if not p.is_file()]

for page in pages:
    if not isinstance(page, str) or page.startswith("/") or ".." in Path(page).parts:
        raise SystemExit(f"unsafe miniapp page path: {page!r}")
    for suffix in (".js", ".wxml", ".wxss"):
        path = MINIAPP / f"{page}{suffix}"
        if not path.is_file():
            missing.append(str(path.relative_to(ROOT)))

if missing:
    raise SystemExit("missing miniapp files: " + ", ".join(sorted(missing)))

print(f"[PASS] miniapp structure valid: {len(pages)} page(s)")
