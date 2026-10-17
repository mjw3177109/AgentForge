import pytest
from agentforge.errors import StateTransitionError
from agentforge.state_machine import TaskStateMachine

def test_valid_transition(): TaskStateMachine.require("READY", "RUNNING")
def test_invalid_transition():
    with pytest.raises(StateTransitionError): TaskStateMachine.require("PENDING", "DONE")
