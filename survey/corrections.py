from collections.abc import Iterable, Mapping

from measure import Point, point
from survey.markers import Marker, MarkerSet
from survey.revisions import get_revision, save_revision
from survey.store import ObservationStore


def amend(store: ObservationStore, revision_id: int, replacements: Iterable[Mapping]) -> int:
    original = get_revision(store, revision_id)
    existing = {marker.position: marker for marker in original.markers.rows}
    edits: dict[Point, Marker] = {}
    try:
        entries = iter(replacements)
    except TypeError as exc:
        raise ValueError('expected marker replacements') from exc
    for entry in entries:
        if not isinstance(entry, Mapping) or set(entry) != {'at', 'category', 'point'}:
            raise ValueError('each correction needs at, category and point')
        old_position = point(entry['at'])
        if old_position not in existing or old_position in edits:
            raise ValueError('correction must select a distinct existing marker position')
        edits[old_position] = Marker(entry['category'], entry['point'])
    if not edits:
        raise ValueError('at least one marker correction is required')
    revised = MarkerSet(tuple(edits.get(position, marker) for position, marker in existing.items()))
    return save_revision(store, original.batch, original.station, revised, parent_id=original.id)
