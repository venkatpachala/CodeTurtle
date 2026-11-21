"""Evidence capture uses real Git data; model quotes cannot manufacture observations."""
import hashlib

import pytest

from core.domain.observations import SourceCitation, SourceObservation
from core.input.snapshot import GitSnapshotProvider
from core.intent.observations import collect_observations
from tests.test_input_snapshot import repository


def test_source_observations_are_revision_bound_and_stable(repository):
    root, base = repository
    provider = GitSnapshotProvider(root)
    snapshot = provider.resolve(base)
    observations, gaps = collect_observations(provider, snapshot, ("app.py",))
    (root / "app.py").write_text("unrelated = True\n")
    assert observations == collect_observations(provider, snapshot, ("app.py",))[0]
    assert not gaps
    assert observations[0].revision_sha == base
    assert observations[1].text == "limit = 2"
    assert observations[1].file_sha256 == hashlib.sha256(b"limit = 2\n").hexdigest()


@pytest.mark.parametrize("changes", [
    {"quote": "limit = 999"}, {"start_line": 2, "end_line": 2}, {"observation_id": "invented"},
])
def test_fabricated_citations_are_rejected(repository, changes):
    root, base = repository
    provider = GitSnapshotProvider(root)
    observations, _ = collect_observations(provider, provider.resolve(base), ("app.py",))
    citation = SourceCitation(**{"observation_id": observations[1].id, "start_line": 1,
                                "end_line": 1, "quote": "limit = 2", **changes})
    with pytest.raises(ValueError):
        citation.validate_against({observation.id: observation for observation in observations})


def test_missing_and_truncated_source_are_not_successful_negative_searches(repository):
    root, base = repository
    provider = GitSnapshotProvider(root)
    observations, gaps = collect_observations(provider, provider.resolve(base),
                                             ("app.py", "missing.py"), max_chars=3)
    assert observations[0].status == "truncated"
    assert observations[-1].status == "absent"
    assert gaps
    with pytest.raises(ValueError, match="unavailable"):
        SourceCitation(observation_id=observations[-1].id, start_line=1, end_line=1,
                       quote="missing").validate_against({item.id: item for item in observations})


def test_modified_excerpt_cannot_load_as_an_original_observation(repository):
    root, base = repository
    provider = GitSnapshotProvider(root)
    observations, _ = collect_observations(provider, provider.resolve(base), ("app.py",))
    data = observations[1].model_dump()
    data["text"] = "limit = 999"
    with pytest.raises(ValueError, match="integrity"):
        SourceObservation.model_validate(data)
