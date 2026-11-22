from collections.abc import Iterable

from analysis.alignment import find_joint_poses
from analysis.outcome import ReviewOutcome, make_outcome
from analysis.projection import project_joint_pairs
from review.bindings import ReviewOrder
from review.received import recheck_bound_pieces


def evaluate(order: ReviewOrder, pieces: Iterable[str]) -> ReviewOutcome:
    received = recheck_bound_pieces(order, pieces)
    witnesses = find_joint_poses(received)
    pairs = project_joint_pairs(witnesses, order.points)
    return make_outcome(order, pairs)
