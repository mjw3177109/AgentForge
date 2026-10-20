"""Safe installer tests; portable, no network, no fixed sandbox paths."""
from __future__ import annotations
from pathlib import Path
import hashlib
import json
import stat
import sys
import zipfile
import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from v4_install import install, InstallDenied
from v4_validate_patch import verify


def sample_zip(tmp_path: Path) -> Path:
    path = tmp_path / 'sample_v4.zip'
    contents = {f'src/agentforge/v4/sample_{i}.py': f'VALUE={i}\n'.encode() for i in range(9)}
    manifest = {'schema': 'agentforge.patch.v4/1',
                'files': {n: hashlib.sha256(blob).hexdigest() for n, blob in contents.items()}}
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name, data in contents.items():
            z.writestr(name, data)
        z.writestr('PATCH_MANIFEST_V40.json', json.dumps(manifest))
    return path


def test_invalid_missing_zip_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr('v4_install._trusted_branch', lambda root: 'feature/v4-test')
    with pytest.raises(FileNotFoundError):
        install(tmp_path, tmp_path / 'not.zip')


def test_existing_changed_file_is_never_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr('v4_install._trusted_branch', lambda root: 'feature/v4-test')
    root = tmp_path / 'repo'
    root.mkdir()
    archive = sample_zip(tmp_path)
    assert verify(str(archive))['status'] == 'VALID_V4_INCREMENTAL_PATCH'
    target = root / 'src/agentforge/v4/sample_0.py'
    target.parent.mkdir(parents=True)
    target.write_text('modified by human')
    with pytest.raises(InstallDenied, match='REFUSE_OVERWRITE'):
        install(root, archive, apply=True)
    assert target.read_text() == 'modified by human'


def test_default_dry_run_never_creates_files(tmp_path, monkeypatch):
    monkeypatch.setattr('v4_install._trusted_branch', lambda root: 'feature/v4-test')
    root = tmp_path / 'repo';root.mkdir()
    archive = sample_zip(tmp_path)
    result = install(root, archive, apply=False)
    assert result['status'] == 'DRY_RUN_OK' and not result['applied']
    assert not (root / 'src/agentforge/v4/sample_0.py').exists()


def test_idempotent_install_and_overwrite_refusal(tmp_path, monkeypatch):
    monkeypatch.setattr('v4_install._trusted_branch', lambda root: 'feature/v4-test')
    root = tmp_path / 'repo';root.mkdir()
    archive = sample_zip(tmp_path)
    first = install(root, archive, apply=True)
    assert first['new'] == 10
    second = install(root, archive, apply=True)
    assert second['new'] == 0 and second['already_identical'] == 10
    (root / 'src/agentforge/v4/sample_1.py').write_text('unrelated work')
    with pytest.raises(InstallDenied, match='REFUSE_OVERWRITE'):
        install(root, archive, apply=True)


def test_rejects_non_v4_branch_without_invoking_installer(tmp_path):
    with pytest.raises(InstallDenied, match='NOT_GIT_REPOSITORY'):
        install(tmp_path, sample_zip(tmp_path))


def test_archive_integrity_rejects_changed_member(tmp_path):
    original = sample_zip(tmp_path)
    changed = tmp_path / 'changed.zip'
    with zipfile.ZipFile(original) as zin, zipfile.ZipFile(changed, 'w') as zout:
        for name in zin.namelist():
            payload = zin.read(name)
            if name.endswith('sample_0.py'):
                payload += b'TAMPERED\n'
            zout.writestr(name, payload)
    got = verify(str(changed))
    assert got['status'] == 'BLOCKED'
    assert any('SHA_MISMATCH' in issue for issue in got['issues'])
