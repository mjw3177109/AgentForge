"""V3 independent evidence collection and verification (opt-in, no runtime hooks)."""
from .v20 import (EXPECTED_V20_GATES, EvidenceValidationError, collect_v20,
                  attest, verify_v20, canonical_json)

__all__ = ["EXPECTED_V20_GATES", "EvidenceValidationError", "collect_v20",
           "attest", "verify_v20", "canonical_json"]
