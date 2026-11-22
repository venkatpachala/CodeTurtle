"""Validate stored artifact hashes and print process measurements, not accuracy."""
from pathlib import Path
import hashlib
import json


def main() -> None:
    root = Path(__file__).resolve().parent
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    for name, expected in manifest["artifacts"].items():
        content = (root / name).read_bytes()
        if hashlib.sha256(content).hexdigest() != expected:
            raise ValueError(f"Artifact integrity mismatch: {name}")
    for name in ("semantic-53337-v4.json", "semantic-53342-latest-v4.json"):
        raw = json.loads((root / name).read_text(encoding="utf-8"))
        result = raw.get("result", raw)
        inspection = result["inspection"]
        print(f"{name}: {result['decision']}, health={result['health']['status']}, "
              f"assessments={inspection['inspected']}/{inspection['eligible']}, "
              f"calls={result['provenance']['budget']['calls']}")
    print("Artifact hashes verified. Real-PR accuracy and merge safety remain unmeasured.")


if __name__ == "__main__":
    main()
