import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from evals.ri import (
    phase1_understanding,
    phase2_analysis,
    phase3_planner,
    phase4_retrieval,
    phase5_specialists,
)

def main(repo: str, number: int):
    reports = []
    for mod in [
        phase1_understanding,
        phase2_analysis,
        phase3_planner,
        phase4_retrieval,
        phase5_specialists,
    ]:
        print("\n" + "=" * 60)
        reports.append(mod.evaluate(repo, number))
    print("\n" + "=" * 60)
    print("SUMMARY")
    for r in reports:
        print(f"  {'PASS' if r.ok else 'FAIL'}  {r.phase}")
    if not all(r.ok for r in reports):
        sys.exit(1)

if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "Graphify-Labs/graphify"
    number = int(sys.argv[2]) if len(sys.argv) > 2 else 2400
    main(repo, number)