from dataclasses import dataclass

from survey.markers import Marker, MarkerSet
from survey.store import ObservationStore


@dataclass(frozen=True, slots=True)
class ObservationRevision:
    id: int
    batch: str
    station: str
    parent_id: int | None
    markers: MarkerSet


def get_revision(store: ObservationStore, revision_id: int) -> ObservationRevision:
    rows = store.read_revision(revision_id)
    if not rows:
        raise LookupError(f'unknown observation revision {revision_id}')
    batch, station, parent_id = rows[0][:3]
    markers = MarkerSet(tuple(Marker(category, (x, y)) for _, _, _, category, x, y in rows))
    return ObservationRevision(revision_id, batch, station, parent_id, markers)


def save_revision(
    store: ObservationStore, batch: str, station: str, markers: MarkerSet,
    parent_id: int | None = None,
) -> int:
    if parent_id is not None:
        parent = get_revision(store, parent_id)
        if (batch, station) != (parent.batch, parent.station):
            raise ValueError('a correction must keep the batch and station of its parent')
    return store.insert_revision(batch, station, markers, parent_id)
