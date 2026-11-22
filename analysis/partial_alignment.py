"""Closed-loop qualification for partial (V2) publications.

A pose is a matched AB / BC / AC candidate triple whose transforms obey
``AB o BC = AC``.  A marker triplet witnesses the pose when the same
station-local records appear simultaneously in AB's B->A match, AC's C->A
match and BC's C->B match.  Endpoint names are unified through the supplied
link materials.  Only poses with at least two distinct witness triplets
qualify; named probes are then transported by the qualified poses.
"""
from dataclasses import dataclass

from overlap.partial_piece import PartialPiece
from overlap.transforms import RigidTransform
from review.points import ReviewPoints


@dataclass(frozen=True, order=True, slots=True)
class PartialPose:
    b_to_a: RigidTransform
    c_to_b: RigidTransform
    c_to_a: RigidTransform
    witnesses: frozenset[tuple[str, str, str]]


def _candidate_rows(piece: PartialPiece):
    rows = []
    for candidate in piece.body['candidates']:
        transform = RigidTransform(*candidate['transform'])
        matches = frozenset((source, target) for source, target in candidate['matches'])
        rows.append((transform, matches))
    return rows


def _resolve_endpoints(
    pieces: dict[str, PartialPiece], link_groups: tuple[frozenset[str], ...],
) -> dict[str, str]:
    canonical: dict[str, str] = {}

    def unite(left: str, right: str) -> None:
        root_left = canonical.get(left, left)
        root_right = canonical.get(right, right)
        chosen = min(root_left, root_right)
        for endpoint in set(canonical) | {left, right}:
            if canonical.get(endpoint, endpoint) in (root_left, root_right):
                canonical[endpoint] = chosen

    for group in link_groups:
        members = sorted(group)
        for other in members[1:]:
            unite(members[0], other)

    def root_of(endpoint: str) -> str:
        return canonical.get(endpoint, endpoint)

    # Confirm every link group references endpoints that actually appear.
    known = {
        endpoint
        for piece in pieces.values()
        for _, matches in _candidate_rows(piece)
        for source, target in matches
        for endpoint in (source, target)
    }
    for group in link_groups:
        for endpoint in group:
            if endpoint not in known:
                raise ValueError('link references an endpoint absent from the pieces')
    return {endpoint: root_of(endpoint) for endpoint in known}


def find_partial_poses(
    pieces: dict[str, PartialPiece], link_groups: tuple[frozenset[str], ...],
) -> tuple[PartialPose, ...]:
    ab, ac, bc = pieces['AB'], pieces['AC'], pieces['BC']
    resolution = _resolve_endpoints(pieces, link_groups)

    def root(endpoint: str) -> str:
        return resolution[endpoint]

    poses: dict[tuple[RigidTransform, RigidTransform, RigidTransform],
                set[tuple[str, str, str]]] = {}
    ac_rows = _candidate_rows(ac)
    for b_to_a, ab_matches in _candidate_rows(ab):
        for c_to_b, bc_matches in _candidate_rows(bc):
            c_to_a = b_to_a.compose(c_to_b)
            for ac_transform, ac_matches in ac_rows:
                if ac_transform != c_to_a:
                    continue
                # Only directed correspondences actually present in each
                # candidate may witness the closed loop.  Resolve edge-local
                # endpoint names through the link equivalence groups.
                ab_pairs = {(root(b_endpoint), root(a_endpoint))
                            for b_endpoint, a_endpoint in ab_matches}
                ac_pairs = {(root(c_endpoint), root(a_endpoint))
                            for c_endpoint, a_endpoint in ac_matches}
                bc_pairs = {(root(c_endpoint), root(b_endpoint))
                            for c_endpoint, b_endpoint in bc_matches}
                a_to_b = {a_record: b_record for b_record, a_record in ab_pairs}
                a_to_c = {a_record: c_record for c_record, a_record in ac_pairs}
                b_to_c = {b_record: c_record for c_record, b_record in bc_pairs}
                witnesses = {
                    (a_record, b_record, c_record)
                    for a_record, b_record in a_to_b.items()
                    if (c_record := a_to_c.get(a_record)) is not None
                    and b_to_c.get(b_record) == c_record
                }
                if len(witnesses) >= 2:
                    poses[(b_to_a, c_to_b, c_to_a)] = witnesses
    return tuple(sorted(
        PartialPose(b_to_a, c_to_b, c_to_a, frozenset(witnesses))
        for (b_to_a, c_to_b, c_to_a), witnesses in poses.items()
    ))


def project_partial_pairs(poses: tuple[PartialPose, ...], points: ReviewPoints):
    pairs = {
        (pose.b_to_a.apply(points.b), pose.c_to_a.apply(points.c))
        for pose in poses
    }
    return tuple(sorted(pairs))
