"""V1.3 runtime provenance guard, not cryptographic provider attestation.

Only the trusted BoundedDeepSeek broker configured for the official HTTPS
endpoint may be used by a run labeled REAL_DEEPSEEK. GitHub logs and the
provider account remain necessary to independently corroborate paid usage.
"""
from urllib.parse import urlsplit

from .guard import BoundaryDenied
from .v05_broker import BoundedDeepSeek


def assert_real_client(client):
    if type(client) is not BoundedDeepSeek:
        raise BoundaryDenied("REAL_DEEPSEEK requires a trusted non-mock broker")
    endpoint = urlsplit(client._endpoint())
    base = urlsplit(client.base_url)
    if (
        base.scheme != "https"
        or base.hostname != "api.deepseek.com"
        or base.port not in (None, 443)
        or base.username is not None
        or base.password is not None
        or bool(base.query) or bool(base.fragment)
        or endpoint.scheme != "https"
        or endpoint.hostname != "api.deepseek.com"
        or endpoint.path not in ("/chat/completions", "/v1/chat/completions")
        or client.model != "deepseek-chat"
        or not isinstance(client.api_key, str) or not client.api_key
        or client.max_attempts != 1
        or type(client.remaining) is not int
        or client.remaining != 5
        or client.calls != 0
    ):
        raise BoundaryDenied("REAL_DEEPSEEK broker violates transport or call policy")
    return True


def valid_provenance(kind, client_checked):
    return kind != "REAL_DEEPSEEK" or client_checked is True
