#!/usr/bin/env python3
"""V2.7 fail-closed read-only permission audit for the dedicated Worker code.

Uses Linux directory file descriptors and no-follow opens. Does not execute
source code, read source/secret contents, access the network, or grant release.
This is a filesystem snapshot, not a signature or remote VM attestation.
"""
import argparse
import json
import os
import stat
from pathlib import Path

REQUIRED_TREES = ("src", "scripts", "examples/django_host", "deploy/v07")
REQUIRED_FILES = ("pyproject.toml",)
DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
MAX_ENTRIES = 50000
MAX_DEPTH = 64


class ScanFailure(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _check_mode(info, *, uid, directory):
    mode = info.st_mode
    correct_type = stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)
    # The code belongs to root and must be readable/traversable by the
    # unprivileged Worker. No group/other write access is ever acceptable.
    visible = bool(mode & stat.S_IROTH)
    if directory:
        visible = visible and bool(mode & stat.S_IXOTH)
    if not correct_type or info.st_uid != uid or mode & 0o022 or not visible:
        raise ScanFailure("SOURCE_ENTRY_UNTRUSTED")


def _checked_directory(parent_fd, name, uid):
    before = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    _check_mode(before, uid=uid, directory=True)
    fd = os.open(name, DIR_FLAGS, dir_fd=parent_fd)
    try:
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            raise ScanFailure("SOURCE_ENTRY_CHANGED_DURING_SCAN")
        _check_mode(after, uid=uid, directory=True)
        return fd
    except BaseException:
        os.close(fd)
        raise


def scan_source(repo, *, expected_root_uid=0, max_entries=MAX_ENTRIES):
    """Audit only source paths that a dedicated worker/stager can load.

    Every directory is opened without following the final symlink, and children
    are inspected relative to their parent fd. A root-owned attacker can still
    replace files AFTER this snapshot; operational change control is required.
    """
    failures = set()
    counts = {"files": 0, "directories": 0}
    fd = None

    def count(key):
        counts[key] += 1
        if counts["files"] + counts["directories"] > max_entries:
            raise ScanFailure("SOURCE_ENTRY_LIMIT_EXCEEDED")

    def walk(fd, depth):
        if depth > MAX_DEPTH:
            raise ScanFailure("SOURCE_TREE_DEPTH_EXCEEDED")
        for name in os.listdir(fd):
            if name in (".", ".."):
                continue
            info = os.stat(name, dir_fd=fd, follow_symlinks=False)
            if stat.S_ISDIR(info.st_mode):
                sub_fd = _checked_directory(fd, name, expected_root_uid)
                try:
                    count("directories")
                    walk(sub_fd, depth + 1)
                finally:
                    os.close(sub_fd)
            else:
                _check_mode(info, uid=expected_root_uid, directory=False)
                count("files")

    def directory_at(base_fd, relative):
        current = os.dup(base_fd)
        try:
            for name in relative.split("/"):
                next_fd = _checked_directory(current, name, expected_root_uid)
                os.close(current)
                current = next_fd
                count("directories")
            return current
        except BaseException:
            os.close(current)
            raise

    try:
        path = Path(repo).absolute()
        # Ensure the repository is not a symlink. The V2.5 gate separately
        # checks the trusted parent, venv, worker identity and secret file.
        info = path.lstat()
        _check_mode(info, uid=expected_root_uid, directory=True)
        fd = os.open(path, DIR_FLAGS)
        after = os.fstat(fd)
        if (info.st_dev, info.st_ino) != (after.st_dev, after.st_ino):
            raise ScanFailure("SOURCE_ENTRY_CHANGED_DURING_SCAN")
        _check_mode(after, uid=expected_root_uid, directory=True)
        count("directories")
        for relative in REQUIRED_TREES:
            root_fd = directory_at(fd, relative)
            try:
                walk(root_fd, 0)
            finally:
                os.close(root_fd)
        for relative in REQUIRED_FILES:
            info = os.stat(relative, dir_fd=fd, follow_symlinks=False)
            _check_mode(info, uid=expected_root_uid, directory=False)
            count("files")
    except ScanFailure as exc:
        failures.add(exc.code)
    except (OSError, ValueError, OverflowError):
        failures.add("SOURCE_SCAN_UNAVAILABLE")
    finally:
        if fd is not None:
            os.close(fd)
    return {
        "schema": "agentforge.django.v27.source-tree-gate.v1",
        "ready_for_unit_staging_only": not failures,
        "failure_codes": sorted(failures),
        "files_inspected": counts["files"],
        "directories_inspected": counts["directories"],
        "source_contents_read": False,
        "secrets_read": False,
        "vm_identity_attested": False,
        "remote_postgres_verified": False,
        "paid_model_calls": 0,
        "production_release_authorized": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="/opt/agentforge/AgentForge")
    args = parser.parse_args()
    report = scan_source(args.repo)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ready_for_unit_staging_only"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
