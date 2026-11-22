"""Exact registration for the partial (V2) handoff edges.

A candidate is an orientation-preserving rigid transform supported by at
least two exact matches of markers that share a category.  The two anchor
matches may belong to different categories, so every ordered pair of
distinct source markers is tried against same-category images.  Every
qualifying transform is retained together with all of its supporting
correspondences.  Only the two local marker tables of the edge are read.
"""
from dataclasses import dataclass

from overlap.transforms import RigidTransform, transform_from_pairs
from survey.markers import Marker, MarkerSet


@dataclass(frozen=True, order=True, slots=True)
class PartialCandidate:
    transform: RigidTransform
    matches: tuple[tuple[Marker, Marker], ...]


def register_partial(
    source: MarkerSet, target: MarkerSet,
) -> tuple[PartialCandidate, ...]:
    target_index: dict[tuple[str, tuple], Marker] = {
        (marker.category, marker.position): marker for marker in target.rows
    }
    target_by_category: dict[str, set[tuple]] = {}
    for marker in target.rows:
        target_by_category.setdefault(marker.category, set()).add(marker.position)

    candidates: dict[RigidTransform, set[tuple[Marker, Marker]]] = {}
    source_rows = source.rows
    for index_first, anchor_first in enumerate(source_rows):
        for index_second, anchor_second in enumerate(source_rows):
            if index_first == index_second:
                continue
            first_images = target_by_category.get(anchor_first.category, set())
            second_images = target_by_category.get(anchor_second.category, set())
            for image_first in first_images:
                for image_second in second_images:
                    if image_first == image_second:
                        continue
                    transform = transform_from_pairs(
                        anchor_first.position, anchor_second.position,
                        image_first, image_second,
                    )
                    if transform is None:
                        continue
                    matches = set()
                    for source_marker in source_rows:
                        image = transform.apply(source_marker.position)
                        target_marker = target_index.get((source_marker.category, image))
                        if target_marker is not None:
                            matches.add((source_marker, target_marker))
                    if len(matches) >= 2:
                        candidates.setdefault(transform, set()).update(matches)

    return tuple(sorted(
        PartialCandidate(transform, tuple(sorted(match_set)))
        for transform, match_set in candidates.items()
    ))
