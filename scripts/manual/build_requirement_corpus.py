"""Author-controlled synthetic development fixtures; never held-out quality evidence."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from core.review.artifacts import write_json_atomic


def main() -> None:
    none_guard = "def size(items):\n    if items is None:\n        return 0\n    return len(items)\n"
    withdrawal = "def withdraw(balance, amount):\n    if amount < 0:\n        raise ValueError('negative amount')\n    return balance - amount\n"
    tenant = "def document(doc, tenant):\n    if doc['tenant'] != tenant:\n        return None\n    return doc\n"
    cases, labels = [], []

    def add(name, before, after, criterion, status, category, *, context=None, context_paths=()):
        files = {"app.py": {"base": before, "head": after}, **(context or {})}
        cases.append({"case_id": name, "files": files, "requirements": [{
            "id": "R1", "description": name.replace("-", " "), "acceptance_criterion": criterion,
            "paths": ["app.py"], "context_paths": list(context_paths),
        }]})
        labels.append({"case_id": name, "requirement_id": "R1", "expected_status": status, "category": category,
                       "annotation_provenance": "author-labelled synthetic fixture"})

    add("none-guard-removed", none_guard, "def size(items):\n    return len(items)\n",
        "size(None) returns zero rather than raising.", "violated", "defect")
    add("none-guard-preserved", none_guard, none_guard.replace("return len(items)", "return (len(items))"),
        "size(None) returns zero rather than raising.", "verified", "clean")
    add("negative-withdrawal", withdrawal, "def withdraw(balance, amount):\n    return balance - amount\n",
        "A negative amount is rejected with ValueError before changing the balance.", "violated", "defect")
    add("equivalent-withdrawal-guard", withdrawal, withdrawal.replace("amount < 0", "not amount >= 0"),
        "A negative amount is rejected with ValueError before changing the balance.", "verified", "clean")
    add("retry-limit-increased", "def max_attempts():\n    return 3\n", "def max_attempts():\n    return 4\n",
        "max_attempts() returns at most three.", "violated", "defect")
    add("intentional-limit-change", "def max_attempts():\n    return 3\n", "def max_attempts():\n    return 5\n",
        "The approved new policy requires max_attempts() to return five.", "verified", "clean")
    add("tenant-filter-removed", tenant, "def document(doc, tenant):\n    return doc\n",
        "document(doc, tenant) never returns a document owned by another tenant.", "violated", "defect")
    add("tenant-guard-delegated", tenant,
        "from policy import visible_document\n\ndef document(doc, tenant):\n    return visible_document(doc, tenant)\n",
        "document(doc, tenant) never returns a document owned by another tenant.", "verified", "clean",
        context={"policy.py": {"base": None, "head": "def visible_document(doc, tenant):\n    return doc if doc['tenant'] == tenant else None\n"}},
        context_paths=("policy.py",))
    add("external-policy-unavailable", "from external_sdk import fetch\n\ndef document(key, tenant):\n    return fetch(key, tenant=tenant)\n",
        "from external_sdk import fetch\n\ndef document(key, tenant):\n    return fetch(key)\n",
        "Documents owned by another tenant cannot be returned; SDK and database policy behavior are unavailable.",
        "unverified", "unresolved", context_paths=("database_policy.json",))
    add("required-field-removed", "def payload(name):\n    return {'name': name, 'active': True}\n",
        "def payload(name):\n    return {'active': True}\n", "payload(name) includes a name key equal to the supplied name.",
        "violated", "defect")
    add("fee-policy-updated", "def fee(amount):\n    return amount * 0.02\n", "def fee(amount):\n    return amount * 0.025\n",
        "The approved new fee is 2.5 percent of amount.", "verified", "clean")
    add("shared-default-list", "def append_item(item, items=None):\n    if items is None:\n        items = []\n    items.append(item)\n    return items\n",
        "def append_item(item, items=[]):\n    items.append(item)\n    return items\n",
        "Calls to append_item(item) without an items argument have independent lists and never retain prior items.",
        "violated", "defect")
    root = Path("benchmark/datasets/requirement_development_v1")
    root.mkdir(parents=True, exist_ok=True)
    write_json_atomic(root / "inputs.json", cases)
    write_json_atomic(root / "labels.json", labels)
    write_json_atomic(root / "manifest.json", {
        "name": "requirement_development_v1", "version": 1, "split": "development", "case_count": len(cases),
        "used_for_system_design": True, "eligible_for_headline_metrics": False,
        "scope": "synthetic contract and integration development; not real PR quality",
        "inputs_sha256": hashlib.sha256((root / "inputs.json").read_bytes()).hexdigest(),
        "labels_sha256": hashlib.sha256((root / "labels.json").read_bytes()).hexdigest(),
    })
    print(f"Wrote {len(cases)} synthetic development cases to {root}")


if __name__ == "__main__":
    main()
