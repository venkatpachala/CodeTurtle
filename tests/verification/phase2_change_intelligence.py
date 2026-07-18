from core.pr_analysis import pr_analysis_agent
from core.state import ReviewState

def verify_change_intelligence():
    """Phase 2 — Change Intelligence Verification"""

    print("=== Change Intelligence Verification ===")

    # Create test state
    state = {
        "title": "fix(runtime): recover stale model and cache state",
        "body": "This PR addresses several issues related to session identifiers...",
        "files_changed": ["agent/model_metadata.py", "agent/transports/codex.py"],
        "full_diff": "..."  # truncated diff
    }

    result = pr_analysis_agent(state)

    print(f"Changed files: {len(result.get('pr_analysis', {}).get('changed_files', []))}")
    print(f"Tests modified: {result.get('pr_analysis', {}).get('tests_added_or_modified', False)}")

    if result.get('pr_analysis'):
        print("Change Intelligence PASSED")
    else:
        print("Change Intelligence FAILED")