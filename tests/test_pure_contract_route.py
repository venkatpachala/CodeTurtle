import json

import pytest

from core.agent.bundle_agent import BundleAgent
from core.intelligence.behavior import compare_pure
from core.runtime.models import Bundle


def bundle():
    before='def f(x):\n    return len(x.encode("utf-8"))\n'
    after='def f(x):\n    return len(x)\n'
    fact=compare_pure(before,after)[0]|{"id":"BX-1"}
    return Bundle(id="B1",paths=["app.py"],units=[{"id":"CU-001","kind":"source","path":"app.py","excerpt":"-return len(x.encode())\n+return len(x)"}],
        requirements=[{"id":"R1","acceptance_criterion":"Return UTF-8 byte length"}],
        change_context={"changes":[{"symbol":"f"}],"behavioral_examples":[{"path":"app.py","examples":[fact]}]})


@pytest.mark.parametrize("side,count,status",[("base",1,"VALID_CANDIDATES"),("head",0,"VALID_EMPTY"),("unknown",0,"PARTIAL")])
def test_contract_choice_uses_backend_operation_and_outcomes_without_self_verification(side,count,status):
    response={"example_id":"BX-1","requirement_id":"R1","expected_side":side,"reason":"Contract interpretation"}
    agent=BundleAgent(llm=lambda _:json.dumps(response),discovery_protocol="semantic")
    result=agent.run_result(bundle())
    assert result.status==status and len(result.candidates)==count
    assert result.request_attempts==1
    if count:
        candidate=result.candidates[0]
        assert candidate.verify_status=="candidate" and candidate.existing_code=="    return len(x)"
        assert candidate.expected!=candidate.actual and candidate.source=="agent"


def test_foreign_example_or_requirement_cannot_create_candidate():
    agent=BundleAgent(llm=lambda _:json.dumps({"example_id":"foreign","requirement_id":"R1","expected_side":"base","reason":"bad"}),discovery_protocol="semantic")
    result=agent.run_result(bundle())
    assert result.status=="INVALID_SCHEMA" and not result.candidates
