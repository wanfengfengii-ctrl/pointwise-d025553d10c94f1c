from collections.abc import Sequence

from overlap.evidence import ROLES, OverlapEvidence, make_evidence, validate_direction
from overlap.handoff import PartialHandoff, PartialHandoffStore, open_partial
from overlap.partial_link import build_partial_links
from overlap.partial_piece import (
    PartialPiece, build_partial_piece, export_partial_piece, verify_partial_piece,
)
from overlap.partial_registration import register_partial
from overlap.registration import register_overlap
from survey.revisions import get_revision
from survey.store import ObservationStore

__all__ = ('freeze', 'freeze_partial', 'open_partial', 'export_partial_links')


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


def _load_handoff(store: ObservationStore, handoff) -> PartialHandoff:
    if not isinstance(store, ObservationStore):
        raise ValueError('partial operations require an ObservationStore')
    if not isinstance(handoff, PartialHandoff):
        raise ValueError('freeze_partial requires an opaque partial handoff handle')
    persisted = PartialHandoffStore(store.connection).read_handoff(handoff.handoff_id)
    if persisted != handoff:
        raise ValueError('partial handoff does not match the station ledger')
    return persisted


def _role_stations(role: str) -> tuple[str, str]:
    if not isinstance(role, str) or role not in ROLES:
        raise ValueError('invalid partial edge role')
    return ROLES[role]


def freeze_partial(store: ObservationStore, handoff: PartialHandoff, role: str) -> str:
    handoff = _load_handoff(store, handoff)
    source_station, target_station = _role_stations(role)
    source = get_revision(store, handoff.revision_for(source_station))
    target = get_revision(store, handoff.revision_for(target_station))
    if (source.station, target.station) != (source_station, target_station):
        raise ValueError('invalid partial edge direction')
    candidates = register_partial(source.markers, target.markers)
    piece = build_partial_piece(handoff, role, source, target, candidates)
    return export_partial_piece(piece)


def export_partial_links(
    store: ObservationStore, handoff: PartialHandoff, pieces: Sequence[str],
) -> tuple[str, ...]:
    handoff = _load_handoff(store, handoff)
    if not isinstance(pieces, Sequence):
        raise ValueError('pieces must be a sequence of partial piece texts')
    for text in pieces:
        piece: PartialPiece = verify_partial_piece(text)
        if piece.handoff_id != handoff.handoff_id or piece.batch != handoff.batch:
            raise ValueError('piece does not belong to this partial handoff')
    return build_partial_links(pieces)
