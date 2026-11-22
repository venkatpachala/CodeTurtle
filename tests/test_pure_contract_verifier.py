import json

import pytest

from core.review.budget import ReviewBudget
from core.runtime.models import Bundle, Candidate
from core.verification.source_verifier import SourceFindingVerifier
from tests.test_input_snapshot import repository
from tests.test_source_finding_verifier import verification_case


BEFORE='def permits(text, limit):\n    return len(text.encode("utf-8")) <= limit\n'
AFTER='def permits(text, limit):\n    return len(text) <= limit\n'
CONTRACT="Accept only when UTF-8 byte length is at most limit"


def case_candidate():
    return Candidate(bundle_id="B1",file="app.py",symbol="permits",start_line=2,
        claim="Non-ASCII input bypasses the byte limit",existing_code="    return len(text) <= limit",
        invariant=CONTRACT,violating_condition="permits(text='é', limit=1)",expected="False",actual="True",
        execution_path=["permits"])


def test_fresh_neutral_contract_check_replays_math_and_resolves_citations(verification_case):
    provider,snapshot=verification_case(before=BEFORE,after=AFTER)
    calls=[]
    def challenge(prompt):
        package=json.loads(prompt.split("\nPACKAGE\n")[1]);calls.append(package)
        assert "candidate" not in package and "base" not in package and "head" not in package
        selected=next(key for key,value in package["options"].items() if value=="False")
        return json.dumps({"selected":selected,"reason":"Two UTF-8 bytes exceed a limit of one"})
    verifier=SourceFindingVerifier(provider,snapshot,lambda _:pytest.fail("generic math/citation generation is unnecessary"),
        ReviewBudget(),contract_complete=challenge)
    bundle=Bundle(id="B1",paths=["app.py"],requirements=[{"id":"R1","acceptance_criterion":CONTRACT,"paths":["app.py"]}])
    assert verifier.verify(case_candidate(),bundle,[])=="VERIFIED"
    record=verifier.records[0]
    assert record.verification_method=="model" and record.source_rule_id==""
    assert record.contract_check.required_value=="False" and len(calls)==1
    record.validate_sources(verifier.observations)
    from core.runtime.models import ReviewResult
    from core.review.contract import ReviewTarget
    with pytest.raises(ValueError,match="explicit user requirement"):
        ReviewResult(target=ReviewTarget(base_sha=snapshot.base_sha,head_sha=snapshot.head_sha),
            source_observations=list(verifier.observations.values()),finding_verifications=[record],
            provenance={"verification_snapshot_id":snapshot.id})
    modified=record.contract_check.model_copy(update={"inputs":{"text":"a","limit":1}})
    with pytest.raises(ValueError,match="replayed"):
        record.model_copy(update={"contract_check":modified}).validate_sources(verifier.observations)


def test_contract_disagreement_is_unresolved_not_verified_refutation(verification_case):
    provider,snapshot=verification_case(before=BEFORE,after=AFTER)
    verifier=SourceFindingVerifier(provider,snapshot,lambda _:pytest.fail("unexpected generic call"),ReviewBudget(),
        contract_complete=lambda _:json.dumps({"selected":"unknown","reason":"Insufficient interpretation"}))
    bundle=Bundle(id="B1",requirements=[{"id":"R1","acceptance_criterion":CONTRACT,"paths":["app.py"]}])
    assert verifier.verify(case_candidate(),bundle,[])=="UNCERTAIN"
    assert verifier.records[0].verdict=="unresolved"


def test_foreign_contract_never_enters_the_pure_verification_route(verification_case):
    provider,snapshot=verification_case(before=BEFORE,after=AFTER)
    from core.verification.pure_contract import supported_transition
    assert supported_transition(case_candidate(),Bundle(id="B1",requirements=[]),provider,snapshot,[]) is None
