import sqlite3

from database import transaction
from measure import entity_id, label, station_name
from survey.markers import MarkerSet


class ObservationStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        with transaction(self.connection):
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS observation_revisions (
                    id INTEGER PRIMARY KEY,
                    batch TEXT NOT NULL,
                    station TEXT NOT NULL CHECK(station IN ('A', 'B', 'C')),
                    parent_id INTEGER,
                    UNIQUE(id, batch, station),
                    FOREIGN KEY(parent_id, batch, station)
                        REFERENCES observation_revisions(id, batch, station)
                )
            ''')
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS observation_markers (
                    revision_id INTEGER NOT NULL REFERENCES observation_revisions(id),
                    ordinal INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    x TEXT NOT NULL,
                    y TEXT NOT NULL,
                    PRIMARY KEY(revision_id, ordinal),
                    UNIQUE(revision_id, x, y)
                )
            ''')

    def insert_revision(
        self, batch: str, station: str, markers: MarkerSet, parent_id: int | None = None,
    ) -> int:
        batch = label(batch, 'batch')
        station = station_name(station)
        if not isinstance(markers, MarkerSet):
            raise ValueError('expected a validated marker table')
        if parent_id is not None:
            parent_id = entity_id(parent_id, 'parent revision number')
        with transaction(self.connection):
            cursor = self.connection.execute(
                'INSERT INTO observation_revisions (batch, station, parent_id) VALUES (?, ?, ?)',
                (batch, station, parent_id),
            )
            revision_id = cursor.lastrowid
            self.connection.executemany('''
                INSERT INTO observation_markers (revision_id, ordinal, category, x, y)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                (revision_id, ordinal, marker.category, str(marker.position[0]), str(marker.position[1]))
                for ordinal, marker in enumerate(markers.rows)
            ))
        return revision_id

    def read_revision(self, revision_id: int) -> list[tuple]:
        revision_id = entity_id(revision_id, 'revision number')
        return self.connection.execute('''
            SELECT r.batch, r.station, r.parent_id, m.category, m.x, m.y
            FROM observation_revisions AS r
            JOIN observation_markers AS m ON m.revision_id = r.id
            WHERE r.id = ?
            ORDER BY m.ordinal
        ''', (revision_id,)).fetchall()
