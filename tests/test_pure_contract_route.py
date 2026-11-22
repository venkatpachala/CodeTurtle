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
    def respond(prompt):
        package=json.loads(prompt.split("\nPACKAGE\n")[1])
        fact=bundle().change_context["behavioral_examples"][0]["examples"][0]
        selected="unknown" if side=="unknown" else next(key for key,value in package["options"].items() if value==fact[side]["value"])
        assert "base" not in package and "head" not in package
        return json.dumps({"requirement_id":"R1","selected":selected,"reason":"Contract interpretation"})
    agent=BundleAgent(llm=respond,discovery_protocol="semantic")
    result=agent.run_result(bundle())
    assert result.status==status and len(result.candidates)==count
    assert result.request_attempts==1
    if count:
        candidate=result.candidates[0]
        assert candidate.verify_status=="candidate" and candidate.existing_code=="    return len(x)"
        assert candidate.expected!=candidate.actual and candidate.source=="agent"


def test_foreign_example_or_requirement_cannot_create_candidate():
    agent=BundleAgent(llm=lambda _:json.dumps({"requirement_id":"R1","selected":"foreign","reason":"bad"}),discovery_protocol="semantic")
    result=agent.run_result(bundle())
    assert result.status=="INVALID_SCHEMA" and not result.candidates
