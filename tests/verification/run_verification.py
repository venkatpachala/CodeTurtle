import sys
import os

# Add project root to path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(project_root)

from verification.phase1_repository_intelligence import verify_repository_intelligence
from verification.phase2_change_intelligence import verify_change_intelligence
from verification.phase3_retrieval import verify_retrieval


def run_all_verification():
    print("=== CodeTurtle Verification Suite ===\n")

    verify_repository_intelligence()
    verify_change_intelligence()
    verify_retrieval()

    print("\nVerification complete.")


if __name__ == "__main__":
    run_all_verification()