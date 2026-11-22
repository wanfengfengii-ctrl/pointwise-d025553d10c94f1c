from collections.abc import Iterable

from overlap.evidence import OverlapEvidence
from overlap.exchange import verify_evidence
from review.bindings import ReviewOrder, ordered_references


def receive_pieces(contents: Iterable[str]) -> dict[str, OverlapEvidence]:
    try:
        received = iter(contents)
    except TypeError as exc:
        raise ValueError('expected the received evidence texts') from exc
    by_role = {}
    for text in received:
        piece = verify_evidence(text)
        if piece.ref.role in by_role:
            raise ValueError('duplicate evidence role')
        by_role[piece.ref.role] = piece
    return by_role


def recheck_bound_pieces(
    order: ReviewOrder, contents: Iterable[str],
) -> dict[str, OverlapEvidence]:
    by_role = receive_pieces(contents)
    references = ordered_references(by_role)
    if order.references != references or order.batch != references[0].batch:
        raise ValueError('received evidence does not match the fixed order')
    return by_role
