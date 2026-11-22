"""Revision-neutral specification questions over backend-computed outcomes."""
import hashlib
from itertools import combinations
from typing import Literal

from pydantic import Field
from core.domain.review_contracts import DomainRecord


class ContractAnswer(DomainRecord):
    selected: Literal["unknown","option_1","option_2"]
    reason: str = Field(min_length=1,max_length=300)


def question(fact: dict, requirements: list[dict], *, challenge=False) -> tuple[dict,dict]:
    values=sorted({fact["base"]["value"],fact["head"]["value"]})
    if bool(int(hashlib.sha256(fact["symbol"].encode()).hexdigest(),16)%2) != challenge:
        values.reverse()
    options={f"option_{i+1}":value for i,value in enumerate(values)}
    input_facts={name:{"character_count":len(value),"utf8_byte_count":len(value.encode("utf-8"))}
                 if isinstance(value,str) else {"element_count":len(value)} if isinstance(value,list) else {}
                 for name,value in fact["inputs"].items()}
    package = {"function":fact["symbol"],"inputs":fact["inputs"],"input_facts":input_facts,
               "requirements":requirements,"options":options}
    integers = sorted((name, value) for name, value in fact["inputs"].items() if type(value) is int)
    if len(integers) >= 2:
        package["integer_relations"] = [
            {"left": left, "right": right, "left_minus_right": a - b, "right_minus_left": b - a}
            for (left, a), (right, b) in combinations(integers, 2)
        ]
    return options, package
