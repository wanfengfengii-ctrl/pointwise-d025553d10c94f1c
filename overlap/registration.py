from overlap.transforms import RigidTransform, transform_from_pairs
from survey.markers import MarkerSet


def register_overlap(source: MarkerSet, target: MarkerSet) -> tuple[RigidTransform, ...]:
    source_groups = source.by_category()
    target_groups = target.by_category()
    if {key: len(group) for key, group in source_groups.items()} != {
        key: len(group) for key, group in target_groups.items()
    }:
        return ()

    # Every valid transform has one ordered image for these two distinct anchors.
    first, second = source.rows[:2]
    candidates = set()
    for image_first in target_groups[first.category]:
        for image_second in target_groups[second.category]:
            transform = transform_from_pairs(
                first.position, second.position, image_first, image_second,
            )
            if transform is not None and all(
                {transform.apply(position) for position in positions} == target_groups[category]
                for category, positions in source_groups.items()
            ):
                candidates.add(transform)
    return tuple(sorted(candidates))
