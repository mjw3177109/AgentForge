#!/usr/bin/env python3
"""Opt-in integration of unchanged P0-P4 ZIPs + P2 CLI on a V3 feature branch.

Default DRY-RUN; --apply writes ONLY new P0-P4 files and the two precise P2
integration edits (autonomous.py and cli.py) after all preflight checks.
No GitHub push, PR merge, production access, or live-model execution.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

BASELINE_SHA = 'fbb4eabab1b42b26ee1f545c38729dadc68541c5'
PACKAGES = {
    'AgentForge_V3_Governance_P0_Additive_Patch.zip': '15945521f41e39563aadb1240bafb68063441efcd7c1c8171f7eb5c5c0c8ef7a',
    'AgentForge_V3_P1_Independent_Evidence_Additive_Patch.zip': '03dbbf53e693cdc37b01fafdfab392b2bc967bac5c7b1352a3a8a4e4c24d93b3',
    'AgentForge_V3_P2_Safe_Repair_Additive_Patch.zip': 'c5b79ce90f800df1dab4546fe61309d5c4c4ef92bba72bf8d351a1a515a51efe',
    'AgentForge_V3_P3_LongTerm_Memory_Additive_Patch.zip': '37cf3e23b8119474280ad3a1a6d140f1a81a3bdf1f4234893a644a280e9bb143',
    'AgentForge_V3_P4_Integration_Acceptance_Additive_Patch.zip': '85da5dac49c6b4dfbbd1a942d9152d745afb18e28b9f5d64c179a99762d80ccb',
}


def _git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(['git', *args], cwd=root, shell=False,
                          capture_output=True, text=True, timeout=20)


def _guard(root: Path):
    branch = _git(root, 'branch', '--show-current').stdout.strip()
    if not branch.startswith(('feature/v3-', 'experiment/v3-')):
        raise ValueError('REFUSE_NON_V3_BRANCH:' + branch)
    if _git(root, 'merge-base', '--is-ancestor', BASELINE_SHA, 'HEAD').returncode:
        raise ValueError('V20_BASELINE_NOT_ANCESTOR')
    # Earlier extraction of this very P4.1 ZIP may leave untracked new files;
    # refuse changes to any tracked source before starting.
    if _git(root, 'diff', '--quiet').returncode or _git(root, 'diff', '--cached', '--quiet').returncode:
        raise ValueError('TRACKED_WORKTREE_NOT_CLEAN')
    for rel in ('src/agentforge/autonomous.py', 'src/agentforge/cli.py'):
        if not (root / rel).is_file() or (root / rel).is_symlink():
            raise ValueError('MISSING_TRUSTED_SOURCE:' + rel)
    return branch


def load_packages(folder: Path) -> tuple[dict[str, bytes], bytes]:
    collected = {}
    p2_installer = None
    for name, digest in PACKAGES.items():
        archive = folder / name
        if not archive.is_file() or archive.is_symlink():
            raise ValueError('MISSING_PATCH_ZIP:' + name)
        if hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
            raise ValueError('PATCH_SHA256_MISMATCH:' + name)
        with zipfile.ZipFile(archive) as z:
            files = [x for x in z.infolist() if not x.is_dir()]
            if len(files) > 100 or sum(x.file_size for x in files) > 3_000_000:
                raise ValueError('PATCH_OVERSIZED:' + name)
            for item in files:
                rel = item.filename
                parts = PurePosixPath(rel).parts
                if (not parts or rel.startswith('/') or '\\' in rel or
                        any(p in ('', '.', '..') for p in parts)):
                    raise ValueError('PATCH_PATH_TRAVERSAL:' + rel)
                kind = (item.external_attr >> 16) & 0o170000
                if kind not in (0, stat.S_IFREG):
                    raise ValueError('PATCH_NON_REGULAR_FILE:' + rel)
                raw = z.read(item)
                if rel in collected and collected[rel] != raw:
                    raise ValueError('CONFLICTING_PATCH_SOURCE:' + rel)
                collected[rel] = raw
                if rel == 'scripts/v3_p2_integrate.py':
                    p2_installer = raw
    if not p2_installer:
        raise ValueError('PINNED_P2_INSTALLER_MISSING')
    return collected, p2_installer


def install(root: Path, packages: Path, *, apply: bool = False) -> dict:
    root = Path(root).resolve(strict=True)
    branch = _guard(root)
    overlay, source = load_packages(Path(packages).resolve(strict=True))
    existing_same = []
    for rel, content in overlay.items():
        target = root / rel
        current = root
        for part in PurePosixPath(rel).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError('SYMLINK_IN_INSTALL_PATH:' + rel)
        if target.exists():
            if not target.is_file() or target.read_bytes() != content:
                raise ValueError('REFUSE_OVERWRITE_EXISTING:' + rel)
            existing_same.append(rel)

    # P2 source comes only from a SHA256-pinned archive; dry-run exact-marker
    # planning BEFORE any writes prevents partial installs on structural drift.
    with tempfile.TemporaryDirectory(prefix='agentforge-p41-installer-') as td:
        script = Path(td) / 'p2_installer.py'
        script.write_bytes(source)
        spec = importlib.util.spec_from_file_location('p41_verified_p2_install', script)
        if spec is None or spec.loader is None:
            raise ValueError('P2_INSTALLER_LOAD_FAILED')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        p2_edits = module.plan_integration(root)
        if not apply:
            return {'status': 'DRY_RUN_OK', 'branch': branch,
                    'new_files': len(overlay) - len(existing_same),
                    'already_matching': len(existing_same),
                    'integrated_code_files': [str(p.relative_to(root)) for p in p2_edits]}
        created = []
        try:
            for rel, data in overlay.items():
                if rel in existing_same:
                    continue
                target = root / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open('xb') as f:
                    f.write(data)
                created.append(target)
            module.install(p2_edits)
        except BaseException:
            for file in reversed(created):
                file.unlink(missing_ok=True)
            raise
        return {'status': 'APPLIED_UNCOMMITTED', 'branch': branch,
                'new_files': len(created), 'already_matching': len(existing_same),
                'integrated_code_files': [str(p.relative_to(root)) for p in p2_edits],
                'next': 'Run full tests; review git diff and commit/push only to feature/v3-*'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo-root', type=Path, default=Path('.'))
    parser.add_argument('--packages-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    try:
        result = install(args.repo_root, args.packages_dir, apply=args.apply)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile) as exc:
        result = {'status': 'BLOCKED', 'reason': str(exc)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['status'] in ('DRY_RUN_OK', 'APPLIED_UNCOMMITTED') else 2


if __name__ == '__main__':
    raise SystemExit(main())
