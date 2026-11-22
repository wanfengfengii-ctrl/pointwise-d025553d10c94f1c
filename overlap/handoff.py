"""Station-side ledger rows for partial (V2) handoffs.

A handoff fixes one frozen observation revision per station A, B and C of
the same batch.  Handoff identifiers are minted per opening so endpoint
identifiers derived from them can never be reused across handoffs.
"""
from dataclasses import dataclass
import secrets

from database import transaction
from measure import entity_id, label, station_name
from survey.revisions import get_revision
from survey.store import ObservationStore

HANDOFF_PREFIX = 'ph-'


@dataclass(frozen=True, slots=True)
class PartialHandoff:
    handoff_id: str
    batch: str
    revisions: tuple[tuple[str, int], ...]

    def revision_for(self, station: str) -> int:
        return dict(self.revisions)[station]


class PartialHandoffStore:
    def __init__(self, connection):
        self.connection = connection

    def initialize(self) -> None:
        with transaction(self.connection):
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS partial_handoffs (
                    handoff_id TEXT PRIMARY KEY,
                    batch TEXT NOT NULL,
                    station_a_revision INTEGER NOT NULL,
                    station_b_revision INTEGER NOT NULL,
                    station_c_revision INTEGER NOT NULL,
                    FOREIGN KEY(station_a_revision) REFERENCES observation_revisions(id),
                    FOREIGN KEY(station_b_revision) REFERENCES observation_revisions(id),
                    FOREIGN KEY(station_c_revision) REFERENCES observation_revisions(id)
                )
            ''')

    def insert_handoff(self, handoff: PartialHandoff) -> None:
        selected = dict(handoff.revisions)
        with transaction(self.connection):
            self.connection.execute('''
                INSERT INTO partial_handoffs
                    (handoff_id, batch, station_a_revision,
                     station_b_revision, station_c_revision)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                handoff.handoff_id, handoff.batch,
                selected['A'], selected['B'], selected['C'],
            ))

    def read_handoff(self, handoff_id: str) -> PartialHandoff:
        row = self.connection.execute('''
            SELECT handoff_id, batch, station_a_revision,
                   station_b_revision, station_c_revision
            FROM partial_handoffs WHERE handoff_id = ?
        ''', (handoff_id,)).fetchone()
        if row is None:
            raise LookupError(f'unknown partial handoff {handoff_id!r}')
        _, batch, rev_a, rev_b, rev_c = row
        return PartialHandoff(handoff_id, batch, (
            ('A', rev_a), ('B', rev_b), ('C', rev_c),
        ))


def endpoint_identifier(handoff_id: str, station: str, ordinal: int) -> str:
    # Endpoint names are handoff-scoped and station-scoped.  The ordinal is
    # the rank of the station-local record over the whole revision, so the
    # same record receives the same name on every edge of the handoff while a
    # new handoff mints an isolated namespace.  Raw coordinates and marker
    # keys never appear in the name.
    return f'ep-{handoff_id[len(HANDOFF_PREFIX):]}-{station}{ordinal:03d}'


def shared_endpoint_index(markers) -> dict[tuple, int]:
    """Stable station-record rank shared by every edge of the handoff."""
    return {marker.position: ordinal for ordinal, marker in enumerate(sorted(markers.rows))}


def open_partial(store: ObservationStore, revisions) -> PartialHandoff:
    if not isinstance(store, ObservationStore):
        raise ValueError('open_partial requires an ObservationStore')
    if not isinstance(revisions, dict) or set(revisions) != {'A', 'B', 'C'}:
        raise ValueError('revisions must map each of A, B and C to one revision number')
    selected: dict[str, int] = {}
    batch = None
    for station in ('A', 'B', 'C'):
        station_name(station)
        revision_id = entity_id(revisions[station], f'{station} revision number')
        revision = get_revision(store, revision_id)
        if revision.station != station:
            raise ValueError(f'revision for {station} belongs to station {revision.station}')
        if batch is None:
            batch = revision.batch
        elif revision.batch != batch:
            raise ValueError('a partial handoff requires one batch')
        selected[station] = revision_id
    label(batch, 'batch')
    handoff = PartialHandoff(
        HANDOFF_PREFIX + secrets.token_hex(16),
        batch,
        tuple((station, selected[station]) for station in ('A', 'B', 'C')),
    )
    handoff_store = PartialHandoffStore(store.connection)
    handoff_store.initialize()
    handoff_store.insert_handoff(handoff)
    return handoff
