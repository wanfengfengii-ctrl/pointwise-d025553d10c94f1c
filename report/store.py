from dataclasses import dataclass
import json
import sqlite3

from analysis.outcome import ReviewOutcome
from database import transaction
from measure import entity_id, pairs_data, point
from overlap.evidence import EvidenceRef
from report.receipts import Receipt, make_receipt
from review.points import bind_points


@dataclass(frozen=True, slots=True)
class ReportSnapshot:
    id: int
    outcome: ReviewOutcome
    receipt: Receipt

    def __post_init__(self):
        if (self.id, self.outcome.order_id) != (self.receipt.report_id, self.receipt.order_id):
            raise ValueError('receipt does not match the report and order')


def _encode_outcome(outcome: ReviewOutcome) -> str:
    snapshot = {
        'batch': outcome.batch,
        'references': [ref.to_dict() for ref in outcome.references],
        'points': outcome.points.to_dict(),
        'status': outcome.status,
        'pairs': pairs_data(outcome.pairs),
    }
    return json.dumps(snapshot, sort_keys=True, separators=(',', ':'))


def _decode_outcome(order_id: int, text: str) -> ReviewOutcome:
    data = json.loads(text)
    references = tuple(EvidenceRef.from_dict(ref) for ref in data['references'])
    pairs = tuple((point(b), point(c)) for b, c in data['pairs'])
    return ReviewOutcome(
        order_id, data['batch'], references, bind_points(data['points']), data['status'], pairs,
    )


class ReportStore:
    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def initialize(self) -> None:
        with transaction(self.connection):
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS reports (
                    id INTEGER PRIMARY KEY,
                    order_id INTEGER NOT NULL REFERENCES review_orders(id),
                    snapshot TEXT NOT NULL
                )
            ''')
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS receipts (
                    report_id INTEGER PRIMARY KEY REFERENCES reports(id),
                    receipt_id TEXT NOT NULL UNIQUE
                )
            ''')

    def commit_publication(self, outcome: ReviewOutcome) -> ReportSnapshot:
        encoded = _encode_outcome(outcome)
        with transaction(self.connection):
            cursor = self.connection.execute(
                'INSERT INTO reports (order_id, snapshot) VALUES (?, ?)',
                (outcome.order_id, encoded),
            )
            receipt = make_receipt(cursor.lastrowid, outcome.order_id)
            self.connection.execute(
                'INSERT INTO receipts (report_id, receipt_id) VALUES (?, ?)',
                (receipt.report_id, receipt.id),
            )
            publication = ReportSnapshot(receipt.report_id, outcome, receipt)
        return publication

    def read_publication(self, report_id: int) -> ReportSnapshot:
        report_id = entity_id(report_id, 'report number')
        row = self.connection.execute('''
            SELECT report.order_id, report.snapshot, receipt.receipt_id
            FROM reports AS report
            JOIN receipts AS receipt ON receipt.report_id = report.id
            WHERE report.id = ?
        ''', (report_id,)).fetchone()
        if row is None:
            raise LookupError(f'unknown report {report_id}')
        order_id, snapshot, receipt_id = row
        return ReportSnapshot(
            report_id, _decode_outcome(order_id, snapshot), Receipt(receipt_id, report_id, order_id),
        )
