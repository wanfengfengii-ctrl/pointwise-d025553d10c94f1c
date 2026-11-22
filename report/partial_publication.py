"""Center-side verification and publication of partial (V2) handoffs."""
import json
from collections.abc import Sequence

from analysis.partial_alignment import find_partial_poses, project_partial_pairs
from measure import label
from overlap.evidence import ROLES
from overlap.partial_link import verify_partial_links
from overlap.partial_piece import PartialPiece, verify_partial_piece
from report.partial_store import (
    ALIGNED, NO_COMMON_REGISTRATION, PartialReportStore, make_partial_receipt,
)
from report.store import ReportStore
from review.points import bind_points


def _receive_pieces(pieces: Sequence[str]) -> dict[str, PartialPiece]:
    if not isinstance(pieces, Sequence):
        raise ValueError('pieces must be a sequence of partial piece texts')
    by_role: dict[str, PartialPiece] = {}
    for text in pieces:
        piece = verify_partial_piece(text)
        if piece.role in by_role:
            raise ValueError('duplicate partial edge role')
        by_role[piece.role] = piece
    if set(by_role) != set(ROLES):
        raise ValueError('partial publication requires the AB, AC and BC roles')
    return {role: by_role[role] for role in ROLES}


def _endpoint_station(endpoint: str, handoff_id: str) -> str | None:
    token = f'ep-{handoff_id[len("ph-"):]}-'
    if not endpoint.startswith(token):
        return None
    station = endpoint[len(token)]
    return station if station in ('A', 'B', 'C') else None


def _check_consistency(pieces: dict[str, PartialPiece]) -> None:
    handoff_ids = {piece.handoff_id for piece in pieces.values()}
    if len(handoff_ids) != 1:
        raise ValueError('mixed partial handoffs cannot be published together')
    batches = {piece.batch for piece in pieces.values()}
    if len(batches) != 1:
        raise ValueError('partial pieces must belong to one batch')
    handoff_id = next(iter(handoff_ids))
    label(next(iter(batches)), 'batch')

    expected_revisions: dict[str, int] = {}
    minted_token = f'ep-{handoff_id[len("ph-"):]}-'
    for role, piece in pieces.items():
        source_station, target_station = ROLES[role]
        for station, revision_id in (
            (source_station, piece.source_revision),
            (target_station, piece.target_revision),
        ):
            if station in expected_revisions and expected_revisions[station] != revision_id:
                raise ValueError(f'station {station} references conflicting frozen revisions')
            expected_revisions[station] = revision_id
        for candidate in piece.body['candidates']:
            for source_endpoint, target_endpoint in candidate['matches']:
                # Only minted names encode the owning station; edge-local
                # renamed endpoints carry their identity in link material.
                if source_endpoint.startswith(minted_token):
                    if _endpoint_station(source_endpoint, handoff_id) != source_station:
                        raise ValueError('endpoint station does not match the edge source')
                if target_endpoint.startswith(minted_token):
                    if _endpoint_station(target_endpoint, handoff_id) != target_station:
                        raise ValueError('endpoint station does not match the edge target')
    if set(expected_revisions) != {'A', 'B', 'C'}:
        raise ValueError('partial publication must cover the three stations')


def _link_identities(links: Sequence[str]) -> tuple[str, ...]:
    identities = []
    for text in links:
        if not isinstance(text, str):
            raise ValueError('expected a link JSON text')
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError('invalid link JSON') from exc
        identity = document.get('id')
        if not isinstance(identity, str) or not identity:
            raise ValueError('invalid link identity')
        identities.append(identity)
    return tuple(identities)


def publish_partial(
    store: ReportStore, pieces: Sequence[str], links: Sequence[str], named_points,
) -> dict:
    if not isinstance(store, ReportStore):
        raise ValueError('publish_partial requires a ReportStore')
    if not isinstance(links, Sequence):
        raise ValueError('links must be a sequence of link JSON texts')
    received = _receive_pieces(pieces)
    _check_consistency(received)
    handoff_id = next(iter({piece.handoff_id for piece in received.values()}))
    piece_ids = {piece.id for piece in received.values()}

    bound_points = bind_points(named_points)
    link_groups = verify_partial_links(links, handoff_id, piece_ids)
    link_references = _link_identities(links)
    if len(set(link_references)) != len(link_references):
        raise ValueError('duplicate link identity')
    poses = find_partial_poses(received, link_groups)
    pair_data = project_partial_pairs(poses, bound_points)
    normalized_pairs = [
        [[str(b[0]), str(b[1])], [str(c[0]), str(c[1])]] for b, c in pair_data
    ]
    status = ALIGNED if normalized_pairs else NO_COMMON_REGISTRATION
    if status == NO_COMMON_REGISTRATION:
        normalized_pairs = []

    partial_store = PartialReportStore(store.connection)
    partial_store.initialize()
    report_id = partial_store.next_report_id()
    archive = {
        'report_id': report_id,
        'handoff_id': handoff_id,
        'batch': received['AB'].batch,
        'references': [received[role].id for role in ROLES],
        'link_references': list(link_references),
        'points': bound_points.to_dict(),
        'status': status,
        'pairs': normalized_pairs,
        'receipt': make_partial_receipt(report_id),
    }
    return partial_store.commit_partial(archive)
