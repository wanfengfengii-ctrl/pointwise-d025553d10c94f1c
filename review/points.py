from collections.abc import Mapping
from dataclasses import dataclass

from measure import Point, point, point_data


@dataclass(frozen=True, slots=True)
class ReviewPoints:
    b: Point
    c: Point

    def __post_init__(self):
        object.__setattr__(self, 'b', point(self.b))
        object.__setattr__(self, 'c', point(self.c))

    def to_dict(self) -> dict[str, list[str]]:
        return {'B': point_data(self.b), 'C': point_data(self.c)}


def bind_points(named_points: Mapping) -> ReviewPoints:
    if not isinstance(named_points, Mapping) or set(named_points) != {'B', 'C'}:
        raise ValueError('review requires exactly one point for B and one for C')
    return ReviewPoints(named_points['B'], named_points['C'])
