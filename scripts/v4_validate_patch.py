#!/usr/bin/env python3
"""Validate V4 incremental ZIP without extracting any contents."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import PurePosixPath
import stat
import zipfile


def verify(archive: str) -> dict:
    issues = []
    with zipfile.ZipFile(archive, 'r') as z:
        names = z.namelist()
        if len(names) != len(set(names)) or len(names) > 50:
            issues.append('DUPLICATE_OR_TOO_MANY_MEMBERS')
        if 'PATCH_MANIFEST_V40.json' not in names:
            issues.append('MISSING_MANIFEST')
            return {'status': 'BLOCKED', 'issues': issues}
        manifest = json.loads(z.read('PATCH_MANIFEST_V40.json'))
        if manifest.get('schema') != 'agentforge.patch.v4/1':
            issues.append('INVALID_PATCH_SCHEMA')
        wanted = manifest.get('files')
        if not isinstance(wanted, dict) or len(wanted) < 8:
            issues.append('INVALID_FILE_LIST')
            wanted = {}
        if set(names) != set(wanted) | {'PATCH_MANIFEST_V40.json'}:
            issues.append('UNEXPECTED_OR_MISSING_CONTENT')
        for info in z.infolist():
            name = info.filename
            parts = PurePosixPath(name).parts
            if (not parts or name.startswith('/') or '\\' in name or ':' in name or
                any(p in ('', '.', '..') for p in parts) or name.endswith('/')):
                issues.append('UNSAFE_ZIP_PATH:' + name)
                continue
            kind = (info.external_attr >> 16) & 0o170000
            if kind not in (0, stat.S_IFREG):
                issues.append('NONREGULAR_ZIP_MEMBER:' + name)
                continue
            if info.file_size > 1024 * 1024:
                issues.append('OVERSIZED_MEMBER:' + name)
                continue
            if name == 'PATCH_MANIFEST_V40.json':
                continue
            if name.startswith(('src/agentforge/v4/', 'tests/test_v4_',
                                 'scripts/v4_', 'docs/V40_', 'examples/v4/',
                                 '.github/workflows/agentforge-v40-', 'PLACEMENT_V40.md')):
                digest = hashlib.sha256(z.read(info)).hexdigest()
                if wanted.get(name) != digest:
                    issues.append('MEMBER_SHA_MISMATCH:' + name)
            else:
                issues.append('NON_V4_FILE:' + name)
    return {'status': 'VALID_V4_INCREMENTAL_PATCH' if not issues else 'BLOCKED',
            'issues': issues, 'file_count': len(names) - 1}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive')
    args = p.parse_args()
    try:
        result = verify(args.archive)
    except (OSError, ValueError, zipfile.BadZipFile, KeyError) as exc:
        result = {'status': 'BLOCKED', 'issues': ['ARCHIVE_INVALID:' + type(exc).__name__]}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] == 'VALID_V4_INCREMENTAL_PATCH' else 2


if __name__ == '__main__':
    raise SystemExit(main())
