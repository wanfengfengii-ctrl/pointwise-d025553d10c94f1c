import json
import sqlite3

from database import transaction
from measure import entity_id
from overlap.evidence import EvidenceRef
from review.bindings import OrderSelection, ReviewOrder
from review.points import bind_points


class OrderStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        with transaction(self.connection):
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS review_orders (
                    id INTEGER PRIMARY KEY,
                    batch TEXT NOT NULL,
                    evidence_refs TEXT NOT NULL,
                    probes TEXT NOT NULL
                )
            ''')

    def insert_order(self, selection: OrderSelection) -> ReviewOrder:
        references = json.dumps([ref.to_dict() for ref in selection.references], sort_keys=True)
        probes = json.dumps(selection.points.to_dict(), sort_keys=True)
        with transaction(self.connection):
            cursor = self.connection.execute(
                'INSERT INTO review_orders (batch, evidence_refs, probes) VALUES (?, ?, ?)',
                (selection.batch, references, probes),
            )
            order_id = cursor.lastrowid
        return ReviewOrder(selection.batch, selection.references, selection.points, order_id)

    def read_order(self, order_id: int) -> ReviewOrder:
        order_id = entity_id(order_id, 'order number')
        row = self.connection.execute(
            'SELECT batch, evidence_refs, probes FROM review_orders WHERE id = ?', (order_id,),
        ).fetchone()
        if row is None:
            raise LookupError(f'unknown review order {order_id}')
        batch, evidence_refs, probes = row
        references = tuple(EvidenceRef.from_dict(ref) for ref in json.loads(evidence_refs))
        return ReviewOrder(batch, references, bind_points(json.loads(probes)), order_id)
