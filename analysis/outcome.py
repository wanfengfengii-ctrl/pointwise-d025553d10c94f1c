from dataclasses import dataclass
from fractions import Fraction

from measure import PointPair, entity_id
from overlap.evidence import ROLES, EvidenceRef
from review.bindings import ReviewOrder
from review.points import ReviewPoints

ALIGNED = 'aligned'
NO_COMMON_REGISTRATION = 'no_common_registration'


@dataclass(frozen=True, slots=True)
class ReviewOutcome:
    order_id: int
    batch: str
    references: tuple[EvidenceRef, ...]
    points: ReviewPoints
    status: str
    pairs: tuple[PointPair, ...]

    def __post_init__(self):
        entity_id(self.order_id, 'order number')
        if not isinstance(self.points, ReviewPoints):
            raise ValueError('outcome must retain the bound review points')
        if (
            not isinstance(self.references, tuple)
            or any(not isinstance(ref, EvidenceRef) for ref in self.references)
            or tuple(ref.role for ref in self.references) != tuple(ROLES)
            or any(ref.batch != self.batch for ref in self.references)
        ):
            raise ValueError('outcome requires three ordered references from its batch')
        if not isinstance(self.pairs, tuple) or any(not _is_point_pair(pair) for pair in self.pairs):
            raise ValueError('outcome pairs must contain exact rational point pairs')
        if self.pairs != tuple(sorted(set(self.pairs))):
            raise ValueError('outcome pairs must be distinct and ordered')
        if self.status != (ALIGNED if self.pairs else NO_COMMON_REGISTRATION):
            raise ValueError('outcome status conflicts with its joint pairs')


def _is_point_pair(value) -> bool:
    return isinstance(value, tuple) and len(value) == 2 and all(
        isinstance(position, tuple) and len(position) == 2
        and all(isinstance(axis, Fraction) for axis in position)
        for position in value
    )


def make_outcome(order: ReviewOrder, pairs: tuple[PointPair, ...]) -> ReviewOutcome:
    status = ALIGNED if pairs else NO_COMMON_REGISTRATION
    return ReviewOutcome(order.id, order.batch, order.references, order.points, status, pairs)
