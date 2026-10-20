"""AgentForge V3 P3: locally isolated, advisory-only engineering memory.

No model invocation, git operation, code execution, workspace mutation, policy
change or PR action. This module intentionally has NO method to apply a repair.
An observed outcome is never proof that the associated strategy caused it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Any

from agentforge.evidence_v3 import canonical_json, verify_v20


class MemorySafetyError(ValueError):
    """Untrusted or contradictory evidence cannot affect policy or suggestions."""


SCHEMA_VERSION = 1
PROJECT_RE = re.compile(r"[A-Za-z0-9_.-]{1,80}/[A-Za-z0-9_.-]{1,100}\Z")
COMMIT_RE = re.compile(r"[0-9a-f]{40}\Z")
FINGERPRINT_RE = re.compile(r"[0-9a-f]{20}\Z")
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
SOURCE_RE = re.compile(r"[A-Za-z0-9_.:-]{1,100}\Z")
MODEL_RE = re.compile(r"[A-Za-z0-9_.:/@-]{1,128}\Z")
MAX_PROFILE_BYTES = 16 * 1024 * 1024

# Only static, reviewed, non-executable guidance can appear in a recommendation.
# Do not add a strategy here that modifies tests, authorization or deployment.
@dataclass(frozen=True)
class Strategy:
    id: str
    category: str
    guidance: str


CATALOG = (
    Strategy("java-declared-type-check", "JAVA_TYPE_ERROR",
             "Read the declared return type and calling code; resolve Optional and imports according to verified business semantics, then rerun the authorized Maven tests."),
    Strategy("java-optional-boundary-review", "JAVA_TYPE_ERROR",
             "Trace Optional-returning API boundaries and documented empty-value semantics; make the smallest authorized correction and rerun the unchanged Maven and behavior gates."),
    Strategy("java-compile-first", "JAVA_COMPILATION",
             "Inspect the exact compiler diagnostics and make only authorized production changes; rerun Maven compile/test and independent contracts."),
    Strategy("java-minimal-change-review", "JAVA_COMPILATION",
             "Review the smallest source diff against existing APIs and imports; keep protected tests untouched and rerun authorized compilation."),
    Strategy("node-build-contract", "NODE_BUILD",
             "Inspect the authorized Vite/Node build error and source contract; rerun the unchanged independent checks."),
    Strategy("test-behavior-contract", "TEST_ASSERTION",
             "Reproduce the independent assertion, correct authorized application behavior, and keep the test fixtures unchanged."),
    Strategy("inspect-unclassified-failure", "UNCLASSIFIED_VERIFICATION",
             "Inspect the independent verification failure; prefer a minimum-scope change and require full unchanged verification."),
)
STRATEGIES = {strategy.id: strategy for strategy in CATALOG}
RETRYABLE_CATEGORIES = frozenset(x.category for x in CATALOG)
BLOCKED_CATEGORIES = frozenset({"NONE", "VERIFICATION_SCOPE_GAP", "JAVA_VERIFICATION_GAP", "TIMEOUT", "ENVIRONMENT"})
KNOWN_CATEGORIES = RETRYABLE_CATEGORIES | BLOCKED_CATEGORIES


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _project(value: str) -> str:
    if not isinstance(value, str) or not PROJECT_RE.fullmatch(value) or any(
        part in {".", ".."} for part in value.split("/")
    ):
        raise MemorySafetyError("Project must be exact owner/repository; traversal denied")
    return value


def _sha(value: str, *, full: bool = True) -> str:
    pattern = COMMIT_RE if full else SHA256_RE
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise MemorySafetyError("Invalid lower-case SHA identifier")
    return value


def _positive(value: int) -> int:
    if type(value) is not int or not 0 < value < 2**63:
        raise MemorySafetyError("Run ID must be a positive integer")
    return value


def _db_path(value: Path) -> Path:
    original = Path(value).expanduser().absolute()
    for parent in (original, *original.parents):
        if parent.is_symlink():
            raise MemorySafetyError("Database path contains symlink")
    if not original.parent.is_dir():
        raise MemorySafetyError("Database parent directory must already exist")
    if original.exists():
        info = original.stat(follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise MemorySafetyError("Database must be a non-hardlinked regular file")
    return original


def trusted_profile_hash(profile: Path) -> str:
    path = Path(profile).absolute()
    for part in (path, *path.parents):
        if part.is_symlink():
            raise MemorySafetyError("Trusted execution profile has symlink component")
    if not path.is_file() or path.stat().st_size > MAX_PROFILE_BYTES:
        raise MemorySafetyError("Trusted execution profile missing/too large")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_diagnosis(payload: dict[str, Any]) -> tuple[str, str, bool]:
    if not isinstance(payload, dict):
        raise MemorySafetyError("Expected P2 diagnosis JSON object")
    category = payload.get("category")
    fingerprint = payload.get("fingerprint")
    retryable = payload.get("retryable")
    if category not in KNOWN_CATEGORIES:
        raise MemorySafetyError("Unknown P2 diagnosis category (never infer permissions)")
    if not isinstance(fingerprint, str) or not FINGERPRINT_RE.fullmatch(fingerprint):
        raise MemorySafetyError("P2 fingerprint must be exactly 20 hex characters")
    if type(retryable) is not bool:
        raise MemorySafetyError("P2 diagnosis must contain boolean retryable")
    if retryable != (category in RETRYABLE_CATEGORIES):
        raise MemorySafetyError("Retry eligibility contradicts reviewed strategy catalog")
    # Ignore all free-form text (guidance, stdout, stderr, traceback, secret fields).
    return category, fingerprint, retryable


class MemoryStore:
    """Local SQLite store. Read methods open SQLite read-only and never mutate it."""

    def __init__(self, path: Path):
        self.path = _db_path(Path(path))

    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        self.path = _db_path(self.path)
        if not self.path.exists():
            raise MemorySafetyError("Memory DB not initialized; run `init` explicitly")
        if read_only:
            # SQLite's URI read-only mode prevents accidental persistent writes.
            db = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=10)
            db.execute("PRAGMA query_only=ON")
        else:
            db = sqlite3.connect(str(self.path), timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        if db.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            db.close()
            raise MemorySafetyError("Unsupported memory schema version; no implicit migrations")
        return db

    def initialize(self) -> None:
        created = not self.path.exists()
        if created:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.path, flags, 0o600)
            os.close(fd)
        with sqlite3.connect(str(_db_path(self.path))) as db:
            existing = db.execute("PRAGMA user_version").fetchone()[0]
            if existing not in (0, SCHEMA_VERSION) or (existing == 0 and not created):
                raise MemorySafetyError("Unrecognized existing database; never modify foreign data")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS diagnoses (
                    project TEXT NOT NULL, profile_sha256 TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, category TEXT NOT NULL,
                    source_id TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(project, profile_sha256, fingerprint, source_id)
                );
                CREATE TABLE IF NOT EXISTS runs (
                    project TEXT NOT NULL, run_id INTEGER NOT NULL,
                    commit_sha TEXT NOT NULL, model_id TEXT NOT NULL,
                    profile_sha256 TEXT NOT NULL, envelope_sha256 TEXT NOT NULL,
                    outcome TEXT NOT NULL CHECK(outcome IN ('PASS', 'FAIL')),
                    rounds_passed INTEGER NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY(project, run_id)
                );
                CREATE TABLE IF NOT EXISTS trials (
                    project TEXT NOT NULL, run_id INTEGER NOT NULL,
                    commit_sha TEXT NOT NULL, profile_sha256 TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, category TEXT NOT NULL,
                    strategy_id TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'PENDING'
                        CHECK(state IN ('PENDING', 'ASSOCIATED_PASS', 'ASSOCIATED_FAIL')),
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(project, run_id)
                );
            """)
            db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            db.commit()

    def observe_diagnosis(self, *, project: str, profile_sha256: str,
                          diagnosis: dict[str, Any], source_id: str) -> dict[str, Any]:
        project = _project(project)
        _sha(profile_sha256, full=False)
        if not isinstance(source_id, str) or not SOURCE_RE.fullmatch(source_id):
            raise MemorySafetyError("Source ID must be short, non-sensitive identifier")
        category, fingerprint, eligible = validate_diagnosis(diagnosis)
        with self._connect() as db:
            cur = db.execute("INSERT OR IGNORE INTO diagnoses VALUES (?,?,?,?,?,?)",
                (project, profile_sha256, fingerprint, category, source_id, _utcnow()))
            # Same project/profile/fingerprint with conflicting category is forbidden.
            categories = db.execute("SELECT DISTINCT category FROM diagnoses "
                "WHERE project=? AND profile_sha256=? AND fingerprint=?",
                (project, profile_sha256, fingerprint)).fetchall()
            if len(categories) != 1 or categories[0]["category"] != category:
                raise MemorySafetyError("Conflicting diagnosis categories for the same fingerprint")
            return {"status": "OBSERVED_UNVERIFIED", "recorded": cur.rowcount == 1,
                    "fingerprint": fingerprint, "category": category,
                    "strategy_suggestions_allowed": eligible,
                    "note": "P2 classification only; not independently verified success"}

    def predeclare_trial(self, *, project: str, profile_sha256: str, run_id: int,
                         commit_sha: str, fingerprint: str, strategy_id: str) -> dict[str, Any]:
        project = _project(project)
        _sha(profile_sha256, full=False)
        _positive(run_id)
        _sha(commit_sha)
        if not isinstance(fingerprint, str) or not FINGERPRINT_RE.fullmatch(fingerprint):
            raise MemorySafetyError("Invalid P2 failure fingerprint")
        strategy = STRATEGIES.get(strategy_id)
        if strategy is None:
            raise MemorySafetyError("Only reviewed, non-executable strategy IDs may be recorded")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM runs WHERE project=? AND run_id=?", (project, run_id)).fetchone():
                raise MemorySafetyError("Cannot retrospectively attach a strategy after evidence ingestion")
            previous = db.execute("SELECT category FROM diagnoses WHERE project=? AND profile_sha256=? "
                "AND fingerprint=? LIMIT 1", (project, profile_sha256, fingerprint)).fetchone()
            if previous is None or previous["category"] != strategy.category:
                raise MemorySafetyError("No matching local P2 diagnosis in this project and policy profile")
            try:
                db.execute("INSERT INTO trials (project,run_id,commit_sha,profile_sha256,"
                           "fingerprint,category,strategy_id,created_at) VALUES (?,?,?,?,?,?,?,?)",
                           (project, run_id, commit_sha, profile_sha256, fingerprint,
                            strategy.category, strategy.id, _utcnow()))
            except sqlite3.IntegrityError as exc:
                raise MemorySafetyError("Trial already declared for this run") from exc
        return {"status": "PENDING_UNVERIFIED", "run_id": run_id,
                "strategy_id": strategy.id, "note": "Trial intent is not proof the strategy was executed"}

    def import_attested_run(self, *, project: str, envelope: dict[str, Any],
                            artifact_dir: Path, trusted_profile: Path,
                            expected_run_id: int, expected_commit_sha: str,
                            expected_model_id: str, expected_key_id: str,
                            secret: bytes, max_age_hours: float = 168.0) -> dict[str, Any]:
        """Verify P1 signature and all enumerated artifacts before recording an outcome.

        P1 returns BLOCKED for an authentic failed 2/3 run. Such a run is stored
        as observed FAIL **only** when there is no extra integrity/auth mismatch.
        """
        project = _project(project)
        _positive(expected_run_id)
        _sha(expected_commit_sha)
        if not isinstance(expected_model_id, str) or not MODEL_RE.fullmatch(expected_model_id):
            raise MemorySafetyError("Model ID must be externally pinned and bounded")
        if not isinstance(expected_key_id, str) or not SOURCE_RE.fullmatch(expected_key_id):
            raise MemorySafetyError("Signer key ID must be independently pinned")
        profile_hash = trusted_profile_hash(trusted_profile)
        report = verify_v20(
            envelope, artifact_dir=artifact_dir, trusted_profile=trusted_profile,
            expected_run_id=expected_run_id, expected_commit_sha=expected_commit_sha,
            expected_model_id=expected_model_id, expected_key_id=expected_key_id,
            secret=secret, max_age_hours=max_age_hours,
        )
        assessment = report.get("assessment")
        if report.get("status") == "VERIFIED_PASS":
            outcome = "PASS"
        elif (report.get("status") == "BLOCKED" and isinstance(assessment, dict)
              and assessment.get("overall") == "FAIL"
              and report.get("issues") == assessment.get("issues")
              and any("RUN_REPORTED_FAILURE:" in issue for issue in assessment.get("issues", []))):
            outcome = "FAIL"
        else:
            # Do not persist any claim or attacker-influenced text on failure.
            raise MemorySafetyError("P1 verification blocked evidence; no memory import allowed")
        if envelope.get("claims", {}).get("trusted_profile_sha256") != profile_hash:
            raise MemorySafetyError("Trusted profile hash mismatch")
        digest = hashlib.sha256(canonical_json(envelope)).hexdigest()
        passed = assessment["rounds_passed"]
        if type(passed) is not int or not 0 <= passed <= 3:
            raise MemorySafetyError("Invalid independent round count")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT * FROM runs WHERE project=? AND run_id=?",
                               (project, expected_run_id)).fetchone()
            if prior:
                if (prior["commit_sha"] != expected_commit_sha or
                    prior["model_id"] != expected_model_id or
                    prior["profile_sha256"] != profile_hash or
                    prior["envelope_sha256"] != digest or prior["outcome"] != outcome):
                    raise MemorySafetyError("Run ID re-use with conflicting trusted evidence")
                inserted = False
            else:
                db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?)",
                    (project, expected_run_id, expected_commit_sha, expected_model_id,
                     profile_hash, digest, outcome, passed, _utcnow()))
                inserted = True
            trial = db.execute("SELECT * FROM trials WHERE project=? AND run_id=?",
                               (project, expected_run_id)).fetchone()
            linked = False
            if trial:
                if trial["commit_sha"] != expected_commit_sha or trial["profile_sha256"] != profile_hash:
                    raise MemorySafetyError("Predeclared strategy bound to different commit or policy")
                db.execute("UPDATE trials SET state=? WHERE project=? AND run_id=?",
                           ("ASSOCIATED_PASS" if outcome == "PASS" else "ASSOCIATED_FAIL",
                            project, expected_run_id))
                linked = True
        return {"status": "IMPORTED_" + outcome, "recorded": inserted, "run_id": expected_run_id,
                "rounds_passed": passed, "strategy_trial_linked": linked,
                "evidence_sha256": digest,
                "note": "P1 evidence verifies a run; correlation is not causation or permission"}

    def recommend(self, *, project: str, profile_sha256: str,
                  diagnosis: dict[str, Any], limit: int = 3) -> dict[str, Any]:
        project = _project(project)
        _sha(profile_sha256, full=False)
        category, fingerprint, eligible = validate_diagnosis(diagnosis)
        if type(limit) is not int or not 1 <= limit <= 5:
            raise MemorySafetyError("Limit must be between 1 and 5")
        if not eligible:
            return {"status": "BLOCKED_FOR_AUTOREPAIR", "category": category,
                    "fingerprint": fingerprint, "recommendations": [],
                    "note": "Authorization, environment and timeout failures require human triage"}
        with self._connect(read_only=True) as db:
            rows = db.execute("SELECT strategy_id, state, run_id FROM trials WHERE project=? "
                "AND profile_sha256=? AND fingerprint=? AND category=? "
                "AND state != 'PENDING'", (project, profile_sha256, fingerprint, category)).fetchall()
        scores: dict[str, dict[str, Any]] = {s.id: {"success": 0, "failure": 0, "run_ids": []}
            for s in CATALOG if s.category == category}
        for row in rows:
            entry = scores.get(row["strategy_id"])
            if entry is None:
                continue
            entry["success" if row["state"] == "ASSOCIATED_PASS" else "failure"] += 1
            entry["run_ids"].append(row["run_id"])
        suggestions = []
        for strategy in CATALOG:
            if strategy.category != category:
                continue
            data = scores[strategy.id]
            # Bayesian smoothing is only a ranking heuristic, not a pass probability.
            heuristic = round((data["success"] + 1) / (data["success"] + data["failure"] + 2), 4)
            suggestions.append({"strategy_id": strategy.id, "guidance": strategy.guidance,
                "associated_passes": data["success"], "associated_failures": data["failure"],
                "observed_run_ids": sorted(data["run_ids"]), "ranking_heuristic": heuristic,
                "evidence_level": "HISTORICAL_ASSOCIATION" if data["run_ids"] else "STATIC_CATALOG"})
        # Repeatedly unsuccessful approaches are suppressed, not simply retried.
        suggestions = [item for item in suggestions
                       if not (item["associated_failures"] >= 2 and item["associated_passes"] == 0)]
        suggestions.sort(key=lambda x: (-x["ranking_heuristic"],
                                         -x["associated_passes"], x["strategy_id"]))
        return {"status": "ADVISORY_ONLY" if suggestions else "NO_SAFE_RECOMMENDATION", "category": category, "fingerprint": fingerprint,
                "recommendations": suggestions[:limit],
                "note": "Never auto-apply, grant write access, override tests, or infer causality"}

    def history(self, *, project: str, limit: int = 20) -> dict[str, Any]:
        project = _project(project)
        if type(limit) is not int or not 1 <= limit <= 100:
            raise MemorySafetyError("History limit must be 1..100")
        with self._connect(read_only=True) as db:
            rows = db.execute("SELECT run_id, commit_sha, outcome, rounds_passed, "
                "model_id, profile_sha256, envelope_sha256 FROM runs WHERE project=? "
                "ORDER BY run_id DESC LIMIT ?", (project, limit)).fetchall()
        return {"project": project, "runs": [dict(row) for row in rows],
                "note": "This is local evidence history, not remote Actions monitoring"}
