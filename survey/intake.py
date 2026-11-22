from collections.abc import Iterable, Mapping

from measure import label, station_name
from survey.markers import Marker, parse_markers
from survey.revisions import save_revision
from survey.store import ObservationStore


def record(
    store: ObservationStore, batch: str, station: str,
    markers: Iterable[Mapping | Marker],
) -> int:
    batch = label(batch, 'batch')
    station = station_name(station)
    table = parse_markers(markers)
    return save_revision(store, batch, station, table)
