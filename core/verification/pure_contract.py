"""Replay a narrow pure transition and independently challenge its user contract."""
from __future__ import annotations

import ast
import json

from core.domain.observations import SourceCitation
from core.intelligence.behavior import build_behavior_context
from core.intelligence.contract_question import question


def supported_transition(candidate, bundle, provider, snapshot, observations):
    if bundle is None:
        return None
    requirements=[r for r in bundle.requirements if candidate.file in r.get("paths",[])
                  and r.get("acceptance_criterion")==candidate.invariant]
    if len(requirements)!=1:
        return None
    try:
        call=ast.parse(candidate.violating_condition,mode="eval").body
        if not isinstance(call,ast.Call) or not isinstance(call.func,ast.Name) or call.func.id!=candidate.symbol or call.args:
            return None
        if len(candidate.violating_condition)>1000 or len(list(ast.walk(call)))>100:
            return None
        inputs={kw.arg:ast.literal_eval(kw.value) for kw in call.keywords if kw.arg is not None}
        if len(inputs)!=len(call.keywords): return None
    except (ValueError,SyntaxError,RecursionError):
        return None
    context=build_behavior_context(provider,snapshot,[candidate.file])
    for group in context:
        for fact in group["examples"]:
            if (fact["symbol"]!=candidate.symbol or json.dumps(inputs,sort_keys=True)!=json.dumps(fact["inputs"],sort_keys=True) or candidate.execution_path!=[candidate.symbol]
                    or candidate.expected!=fact["base"]["value"] or candidate.actual!=fact["head"]["value"]
                    or candidate.existing_code!=fact["head_operation"] or candidate.start_line!=fact["head_line"]):
                continue
            citations=[]
            for side in ("base","head"):
                start=fact[side+"_line"];code=fact[side+"_operation"]
                end=start+len(code.splitlines())-1
                observation=next((obs for obs in observations if obs.path==candidate.file and obs.revision_side==side
                                  and obs.status=="success" and obs.start_line<=start<=end<=obs.end_line),None)
                if observation is None: return None
                citation=SourceCitation(observation_id=observation.id,start_line=start,end_line=end,quote=code)
                citation.validate_against({obs.id:obs for obs in observations});citations.append(citation)
            options,package=question(fact,requirements,challenge=True)
            return {"options":options,"package":package,"fact":fact,"requirement":requirements[0],"citations":citations}
    return None
