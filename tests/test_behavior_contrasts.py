from pathlib import Path

import pytest

from core.intelligence.behavior import compare_pure


def test_utf8_counterexample_and_repair_have_opposite_factual_outputs():
    correct='def permits(text, limit):\n    return len(text.encode("utf-8")) <= limit\n'
    broken='def permits(text, limit):\n    return len(text) <= limit\n'
    forward=compare_pure(correct,broken)
    reverse=compare_pure(broken,correct)
    assert forward and reverse
    fact=forward[0]
    assert fact["inputs"]=={"text":"é","limit":1}
    assert fact["base"]["value"]=="False" and fact["head"]["value"]=="True"
    assert reverse[0]["base"]==fact["head"] and reverse[0]["head"]==fact["base"]


def test_pagination_counterexample_computes_count_not_end_index():
    correct='def page(items, start, count):\n    return items[start:start+count]\n'
    broken='def page(items, start, count):\n    return items[start:count]\n'
    fact=compare_pure(correct,broken)[0]
    assert fact["inputs"]=={"items":["a","b","c","d"],"start":1,"count":1}
    assert fact["base"]["value"]=="['b']" and fact["head"]["value"]=="[]"


@pytest.mark.parametrize("source",[
    'import os\ndef f(x):\n    return len(x)\n',
    'len = custom\ndef f(x):\n    return len(x)\n',
    'def f(len):\n    return len(1)\n',
    '@decorator\ndef f(x):\n    return len(x)\n',
    'def f(x=side_effect()):\n    return len(x)\n',
    'def f(x: side_effect()):\n    return len(x)\n',
    'def f(x):\n    return x.danger()\n',
    'def f(x):\n    return [i for i in x]\n',
    'def f(x):\n    while True: pass\n',
])
def test_unsupported_effects_bindings_or_syntax_abstain(source):
    assert compare_pure(source,'def f(x):\n    return len(x)\n')==[]


def test_repository_code_cannot_execute_during_ast_analysis(tmp_path):
    marker=tmp_path/"escape"
    source=f'def f(x):\n    return __import__("pathlib").Path({str(marker)!r}).write_text("bad")\n'
    assert compare_pure(source,'def f(x):\n    return 0\n')==[]
    assert not marker.exists()


def test_sample_and_output_limits_are_enforced():
    assert compare_pure('def f(x):\n    return len(x)\n','def f(x):\n    return 1\n',max_samples=0)==[]
    assert len(compare_pure('def f(x):\n    return len(x)\n','def f(x):\n    return 1\n',max_facts=1))<=1


def test_subset_limits_never_become_python_exception_evidence():
    facts = compare_pure("def f(x):\n    return x + x", "def f(x):\n    return x")
    assert facts and all(fact["base"]["kind"] == "return_value" for fact in facts)
    assert all(type(fact["inputs"]["x"]) is int for fact in facts)


def test_tuple_and_list_outputs_retain_distinct_python_types():
    fact = compare_pure("def f(x):\n    return (x,)", "def f(x):\n    return [x]")[0]
    assert fact["base"]["value"] == "(None,)"
    assert fact["head"]["value"] == "[None]"


def test_ordered_comparison_samples_both_operands_as_integers():
    facts = compare_pure("def ready(a, b):\n    return a >= b", "def ready(a, b):\n    return a > b")
    assert facts and all(type(v) is int for f in facts for v in f["inputs"].values())


def test_integer_relations_remain_identical_when_challenge_reverses_options():
    from core.intelligence.contract_question import question

    fact = compare_pure("def change(x, y):\n    return x-y", "def change(x, y):\n    return y-x")[0]
    first_options, first = question(fact, [])
    second_options, second = question(fact, [], challenge=True)
    assert first_options["option_1"] == second_options["option_2"]
    assert first["integer_relations"] == second["integer_relations"] == [
        {"left": "x", "right": "y", "left_minus_right": -1, "right_minus_left": 1}
    ]
