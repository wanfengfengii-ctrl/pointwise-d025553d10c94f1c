from collections.abc import Mapping
from dataclasses import dataclass

from overlap.evidence import ROLES, EvidenceRef, OverlapEvidence
from review.points import ReviewPoints


@dataclass(frozen=True, slots=True)
class OrderSelection:
    batch: str
    references: tuple[EvidenceRef, ...]
    points: ReviewPoints


@dataclass(frozen=True, slots=True)
class ReviewOrder(OrderSelection):
    id: int


def ordered_references(pieces: Mapping[str, OverlapEvidence]) -> tuple[EvidenceRef, ...]:
    if set(pieces) != set(ROLES):
        raise ValueError('review requires the AB, AC and BC roles')
    references = tuple(pieces[role].ref for role in ROLES)
    if len({ref.batch for ref in references}) != 1:
        raise ValueError('review pieces must belong to a single batch')
    return references


def bind_order(pieces: Mapping[str, OverlapEvidence], points: ReviewPoints) -> OrderSelection:
    references = ordered_references(pieces)
    return OrderSelection(references[0].batch, references, points)
