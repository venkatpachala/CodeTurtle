"""Isolated native finding-gate diagnostic; author-labeled synthetic cases."""
import hashlib
import json
from pathlib import Path
import subprocess
import time

from config import settings
from core.gateway.gateway import AIGateway
from core.input.snapshot import GitSnapshotProvider
from core.runtime.models import Candidate
from core.review.budget import ReviewBudget
from core.domain.finding_verification import FindingDecision
from core.verification.source_verifier import SourceFindingVerifier

import os
OUTPUT = Path(os.environ.get('CODETURTLE_DIAGNOSTIC_OUTPUT', '.validation/native-finding-replay')).resolve()
OUTPUT.mkdir(parents=True, exist_ok=True)
PROTECTED = 'def size(items):\n    if items is None:\n        return 0\n    return len(items)\n'
BROKEN = 'def size(items):\n    return len(items)\n'
PRESERVED = 'def size(items):\n    """Count items, treating None as empty."""\n    if items is None:\n        return 0\n    return len(items)\n'

def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True, capture_output=True, text=True).stdout.strip()

summary = []
for name, head_text, expected in [('removed-guard', BROKEN, 'supported'), ('preserved-guard', PRESERVED, 'refuted')]:
    root = OUTPUT / ('final-' + name)
    root.mkdir(exist_ok=False)
    git(root, 'init')
    git(root, 'config', 'user.name', 'CodeTurtle diagnostic')
    git(root, 'config', 'user.email', 'diagnostic@example.invalid')
    (root / 'app.py').write_text(PROTECTED)
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'base input')
    base = git(root, 'rev-parse', 'HEAD')
    (root / 'app.py').write_text(head_text)
    git(root, 'commit', '-am', 'head input')
    provider = GitSnapshotProvider(root)
    snapshot = provider.resolve(base)
    candidate = Candidate(bundle_id='B1', file='app.py', symbol='size', start_line=len(head_text.splitlines()), candidate_id='C-001',
        title='None input raises TypeError', claim='size(None) raises TypeError after the guard is removed',
        invariant='size(None) returns zero', violating_condition='items is None', expected='0', actual='TypeError',
        existing_code='return len(items)', execution_path=['size'], evidence=['app.py'], evidence_paths=['app.py'])
    calls, metadata = [], {}
    def complete(prompt):
        response = AIGateway().generate(prompt=prompt, capability='correctness_review',
            agent_name='FindingVerifier:structured', temperature=0.0, max_tokens=1400, retries=0,
            response_schema=FindingDecision)
        metadata.clear()
        metadata.update(response.telemetry.model_dump(mode='json'))
        calls.append(dict(metadata))
        return str(response.content or '')
    budget = ReviewBudget()
    verifier = SourceFindingVerifier(provider, snapshot, complete, budget, generation_metadata=lambda: metadata)
    start = time.monotonic()
    outcome = verifier.verify(candidate, None, [])
    result = {'purpose':'isolated development candidate replay; not end-to-end discovery or held-out evaluation',
        'case':name, 'expected_author_label':expected, 'reviewer_commit':git(Path.cwd(), 'rev-parse','HEAD'),
        'reviewer_dirty':bool(git(Path.cwd(), 'status','--porcelain','--untracked-files=no')),
        'snapshot':snapshot.model_dump(mode='json'), 'base_source':PROTECTED,'head_source':head_text,
        'candidate':candidate.to_dict(), 'outcome':outcome, 'wall_seconds':time.monotonic()-start,
        'verification':[record.model_dump(mode='json') for record in verifier.records],
        'observations':[record.model_dump(mode='json') for record in verifier.observations.values()],
        'calls':calls,'budget':budget.to_dict(), 'dollar_cost_measured':False}
    (OUTPUT / ('final-' + name + '.json')).write_text(json.dumps(result,indent=2)+'\n')
    summary.append({'case':name,'expected':expected,'outcome':outcome,'status':verifier.records[0].status,
                    'verdict':verifier.records[0].verdict,'calls':len(calls),'wall_seconds':result['wall_seconds']})
    print(json.dumps(summary[-1]),flush=True)
(OUTPUT / 'final-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
