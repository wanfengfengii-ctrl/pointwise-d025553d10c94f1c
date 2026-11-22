from collections.abc import Iterator, Mapping
from dataclasses import dataclass

from overlap.evidence import OverlapEvidence
from overlap.transforms import RigidTransform


@dataclass(frozen=True, slots=True)
class PoseWitness:
    b_to_a: RigidTransform
    c_to_a: RigidTransform


def find_joint_poses(pieces: Mapping[str, OverlapEvidence]) -> Iterator[PoseWitness]:
    ac = set(pieces['AC'].transforms)
    if not ac:
        return
    for b_to_a in pieces['AB'].transforms:
        for c_to_b in pieces['BC'].transforms:
            c_to_a = b_to_a.compose(c_to_b)
            if c_to_a in ac:
                yield PoseWitness(b_to_a, c_to_a)
