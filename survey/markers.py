from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from measure import Point, label, point


@dataclass(frozen=True, order=True, slots=True)
class Marker:
    category: str
    position: Point

    def __post_init__(self):
        object.__setattr__(self, 'category', label(self.category, 'marker category'))
        object.__setattr__(self, 'position', point(self.position))


@dataclass(frozen=True, slots=True)
class MarkerSet:
    rows: tuple[Marker, ...]

    def __post_init__(self):
        rows = tuple(self.rows)
        if len(rows) < 2 or any(not isinstance(row, Marker) for row in rows):
            raise ValueError('at least two valid marker positions are required')
        if len({row.position for row in rows}) != len(rows):
            raise ValueError('duplicate marker position')
        object.__setattr__(self, 'rows', tuple(sorted(rows)))

    def by_category(self) -> dict[str, set[Point]]:
        groups: dict[str, set[Point]] = {}
        for marker in self.rows:
            groups.setdefault(marker.category, set()).add(marker.position)
        return groups


def parse_markers(rows: Iterable[Mapping | Marker]) -> MarkerSet:
    try:
        supplied_rows = iter(rows)
    except TypeError as exc:
        raise ValueError('expected a marker table') from exc
    parsed = []
    for row in supplied_rows:
        if isinstance(row, Marker):
            parsed.append(row)
        elif isinstance(row, Mapping) and set(row) == {'category', 'point'}:
            parsed.append(Marker(row['category'], row['point']))
        else:
            raise ValueError('each marker needs category and point')
    return MarkerSet(tuple(parsed))
