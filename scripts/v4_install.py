#!/usr/bin/env python3
"""SHA-checked V4 additive installer for isolated feature/v4-* branches.

Default DRY RUN. Will not replace a nonmatching existing file, even with --apply.
Existing V2/V3 AgentForge sources are never in the archive whitelist.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import zipfile

from v4_validate_patch import verify

BASELINE_SHA = 'fbb4eabab1b42b26ee1f545c38729dadc68541c5'


class InstallDenied(ValueError):
    pass


def _git(repo: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run(['git', *args], cwd=repo, check=False,
                          capture_output=True, text=True, timeout=20, shell=False)


def _trusted_branch(root: Path) -> str:
    if (root / '.git').is_symlink() or not (root / '.git').exists():
        raise InstallDenied('NOT_GIT_REPOSITORY')
    branch = _git(root, 'branch', '--show-current')
    if branch.returncode or not branch.stdout.strip().startswith(('feature/v4-', 'experiment/v4-')):
        raise InstallDenied('NOT_V4_ISOLATED_BRANCH')
    base = _git(root, 'merge-base', '--is-ancestor', BASELINE_SHA, 'HEAD')
    if base.returncode:
        raise InstallDenied('BASELINE_NOT_ANCESTOR')
    for argv in (('diff', '--quiet'), ('diff', '--cached', '--quiet')):
        if _git(root, *argv).returncode:
            raise InstallDenied('TRACKED_WORKTREE_NOT_CLEAN')
    return branch.stdout.strip()


def install(repo: Path, archive: Path, *, apply: bool = False) -> dict:
    root = Path(repo).resolve(strict=True)
    branch = _trusted_branch(root)
    source_path = Path(archive).absolute()
    if source_path.is_symlink():
        raise InstallDenied('PATCH_ARCHIVE_SYMLINK_DENIED')
    p = source_path.resolve(strict=True)
    if not p.is_file():
        raise InstallDenied('PATCH_ARCHIVE_INVALID')
    inspection = verify(str(p))
    if inspection['status'] != 'VALID_V4_INCREMENTAL_PATCH':
        raise InstallDenied('INVALID_V4_PATCH:' + ','.join(inspection['issues']))
    prepared, same = [], []
    with zipfile.ZipFile(p) as z:
        items = [(n, z.read(n)) for n in z.namelist() if n != 'PATCH_MANIFEST_V40.json']
        items.append(('PATCH_MANIFEST_V40.json', z.read('PATCH_MANIFEST_V40.json')))
        for name, data in items:
            cursor = root
            for segment in PurePosixPath(name).parts:
                cursor = cursor / segment
                if cursor.is_symlink():
                    raise InstallDenied('SYMLINK_INSTALL_PATH:' + name)
            if cursor.exists():
                if not cursor.is_file() or cursor.read_bytes() != data:
                    raise InstallDenied('REFUSE_OVERWRITE:' + name)
                same.append(name)
            else:
                prepared.append((cursor, data))
        if not apply:
            return {'status': 'DRY_RUN_OK', 'branch': branch, 'new': len(prepared),
                    'already_identical': len(same), 'applied': False}
        created = []
        try:
            for path, content in prepared:
                path.parent.mkdir(parents=True, exist_ok=True)
                # Recheck symlink chains after mkdir; no force/overwrite option.
                cursor = root
                for segment in path.relative_to(root).parts:
                    cursor = cursor / segment
                    if cursor.is_symlink():
                        raise InstallDenied('SYMLINK_RACE_DENIED')
                with path.open('xb') as f:
                    f.write(content)
                    f.flush()
                    os.fsync(f.fileno())
                created.append(path)
        except BaseException:
            for file in reversed(created):
                file.unlink(missing_ok=True)
            raise
    return {'status': 'APPLIED_UNCOMMITTED', 'branch': branch, 'new': len(created),
            'already_identical': len(same), 'applied': True,
            'next': 'Run all offline tests, review git diff, commit only after human approval'}


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo-root', type=Path, default=Path('.'))
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--apply', action='store_true')
    args = p.parse_args(argv)
    try:
        result = install(args.repo_root, args.archive, apply=args.apply)
        code = 0
    except (OSError, ValueError, subprocess.TimeoutExpired, zipfile.BadZipFile) as exc:
        result = {'status': 'BLOCKED', 'reason': str(exc)}
        code = 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
