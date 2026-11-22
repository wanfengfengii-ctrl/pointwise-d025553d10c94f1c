from collections.abc import Iterable

from analysis.alignment import PoseWitness
from measure import PointPair
from review.points import ReviewPoints


def project_joint_pairs(
    witnesses: Iterable[PoseWitness], points: ReviewPoints,
) -> tuple[PointPair, ...]:
    pairs = {
        (witness.b_to_a.apply(points.b), witness.c_to_a.apply(points.c))
        for witness in witnesses
    }
    return tuple(sorted(pairs))
