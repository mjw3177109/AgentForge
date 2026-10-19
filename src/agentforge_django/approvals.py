"""Bind a human approval to the exact request and project configuration."""

import hashlib
import json


def _sha(data):
    payload = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def approval_digests(job):
    project = job.project
    request = {
        "job_id": str(job.pk),
        "mode": job.mode,
        "request": job.request,
        "project_id": project.pk,
    }
    configuration = {
        "root_path": project.root_path,
        "enabled": project.enabled,
        "autonomous_enabled": project.autonomous_enabled,
        "base_branch": project.base_branch,
        "profiles_path": project.profiles_path,
        "write_scopes": project.write_scopes,
        "run_business_tests": project.run_business_tests,
    }
    return _sha(request), _sha(configuration)
