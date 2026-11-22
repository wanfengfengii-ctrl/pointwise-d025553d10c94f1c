from overlap.evidence import OverlapEvidence, make_evidence, validate_direction
from overlap.registration import register_overlap
from survey.revisions import get_revision
from survey.store import ObservationStore


def freeze(
    store: ObservationStore, role: str, source_revision: int, target_revision: int,
) -> OverlapEvidence:
    source = get_revision(store, source_revision)
    target = get_revision(store, target_revision)
    validate_direction(role, source.station, target.station)
    if source.batch != target.batch:
        raise ValueError('overlap revisions must belong to the same batch')
    transforms = register_overlap(source.markers, target.markers)
    return make_evidence(
        source.batch, role, source.station, source.id, target.station, target.id, transforms,
    )
