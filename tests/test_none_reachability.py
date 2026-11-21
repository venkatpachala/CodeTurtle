"""The consistency checker must return unknown outside its small language."""
import pytest

from core.verification.reachability import none_trigger_reaches_anchor

GUARDED = "def size(items):\n    if items is None:\n        return 0\n    return len(items)\n"


@pytest.mark.parametrize("trigger", ["items is None", "size(None)", "pkg.size(None)"])
def test_exact_none_bindings_follow_the_active_guard(trigger):
    assert none_trigger_reaches_anchor(GUARDED, "size", trigger, "return len(items)") == (True, False)


@pytest.mark.parametrize("trigger", ["items is None or items == 4", "not (items is None)",
                                    "items is None is False", "size(None) or size(4)",
                                    "when items is None, perhaps another path"])
def test_compound_or_free_text_triggers_do_not_prove_unreachability(trigger):
    assert none_trigger_reaches_anchor(GUARDED, "size", trigger, "return len(items)") == (True, None)


@pytest.mark.parametrize("source", [
    "@decorator\n" + GUARDED,
    "def size(items):\n    items = transform(items)\n    return len(items)\n",
    "def size(items):\n    for value in items:\n        pass\n    return len(items)\n",
    "def size(items, flag=False):\n    if flag:\n        return 0\n    return len(items)\n",
    GUARDED + "\n" + GUARDED,
])
def test_unsupported_flow_and_ambiguous_symbols_stay_unknown(source):
    assert none_trigger_reaches_anchor(source, "size", "items is None", "return len(items)") == (True, None)
