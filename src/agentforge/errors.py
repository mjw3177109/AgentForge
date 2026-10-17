class AgentForgeError(Exception):
    """Base AgentForge exception."""

class ProtocolError(AgentForgeError): pass
class PolicyDenied(AgentForgeError): pass
class EvidenceError(AgentForgeError): pass
class StateTransitionError(AgentForgeError): pass
