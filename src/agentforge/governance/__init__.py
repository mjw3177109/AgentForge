"""Optional, read-only V3 governance preflight; no runtime integration by default."""
from .preflight import assess, ProposedChange, PreflightResult

__all__ = ["assess", "ProposedChange", "PreflightResult"]
