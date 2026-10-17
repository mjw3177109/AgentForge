from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
import time
import httpx
import jwt


@dataclass
class GitHubAppClient:
    """Minimal GitHub App client for delivery/read-only CI observation.

    Deliberately no merge endpoint is exposed here. The delivery layer may open
    a PR and inspect CI, but merging the default branch remains a separate,
    explicit human/control-plane action.
    """

    app_id: str
    installation_id: str
    private_key: str
    api_base: str = "https://api.github.com"
    api_version: str = "2026-03-10"
    timeout: int = 30
    client: httpx.Client | None = None
    _token: str | None = field(default=None, init=False, repr=False)
    _token_expires_at: float = field(default=0.0, init=False, repr=False)

    def _app_jwt(self) -> str:
        now = int(time.time())
        payload = {"iat": now - 60, "exp": now + 540, "iss": self.app_id}
        return jwt.encode(payload, self.private_key, algorithm="RS256")

    def _request(self, method: str, path: str, *, headers: dict | None = None, json: Any = None) -> httpx.Response:
        url = f"{self.api_base.rstrip('/')}/{path.lstrip('/')}"
        if self.client is not None:
            response = self.client.request(method, url, headers=headers, json=json)
        else:
            with httpx.Client(timeout=self.timeout) as client:
                response = client.request(method, url, headers=headers, json=json)
        response.raise_for_status()
        return response

    def installation_token(self, force_refresh: bool = False) -> str:
        if not force_refresh and self._token and time.time() < self._token_expires_at - 60:
            return self._token
        headers = {
            "Authorization": f"Bearer {self._app_jwt()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.api_version,
        }
        data = self._request(
            "POST",
            f"app/installations/{self.installation_id}/access_tokens",
            headers=headers,
        ).json()
        self._token = data["token"]
        self._token_expires_at = time.time() + 50 * 60
        return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.installation_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self.api_version,
        }

    def get_repository(self, owner: str, repo: str) -> dict:
        return self._request("GET", f"repos/{owner}/{repo}", headers=self._headers()).json()

    def create_pull_request(self, owner: str, repo: str, head: str, base: str, title: str, body: str, draft: bool = False) -> dict:
        payload = {"title": title, "head": head, "base": base, "body": body, "draft": draft}
        return self._request("POST", f"repos/{owner}/{repo}/pulls", headers=self._headers(), json=payload).json()

    def get_pull_request(self, owner: str, repo: str, number: int) -> dict:
        return self._request("GET", f"repos/{owner}/{repo}/pulls/{number}", headers=self._headers()).json()

    def get_combined_status(self, owner: str, repo: str, sha: str) -> dict:
        return self._request("GET", f"repos/{owner}/{repo}/commits/{sha}/status", headers=self._headers()).json()

    def get_check_runs(self, owner: str, repo: str, sha: str) -> dict:
        headers = {**self._headers(), "Accept": "application/vnd.github+json"}
        return self._request("GET", f"repos/{owner}/{repo}/commits/{sha}/check-runs", headers=headers).json()

    def ci_snapshot(self, owner: str, repo: str, sha: str) -> dict:
        status = self.get_combined_status(owner, repo, sha)
        checks = self.get_check_runs(owner, repo, sha)
        runs = checks.get("check_runs", [])
        unfinished = [r for r in runs if r.get("status") != "completed"]
        failed = [
            r for r in runs
            if r.get("status") == "completed" and r.get("conclusion") not in {"success", "neutral", "skipped"}
        ]
        if failed or status.get("state") in {"failure", "error"}:
            state = "FAILURE"
        elif unfinished or status.get("state") == "pending":
            state = "PENDING"
        elif runs or status.get("statuses"):
            state = "SUCCESS"
        else:
            state = "NO_CHECKS"
        return {
            "state": state,
            "combined_status": status.get("state"),
            "check_runs": [
                {"name": r.get("name"), "status": r.get("status"), "conclusion": r.get("conclusion")}
                for r in runs
            ],
        }
