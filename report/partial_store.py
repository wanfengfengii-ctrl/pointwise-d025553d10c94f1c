"""Center ledger tables and one-shot persistence for partial publications."""
import json

from database import transaction
from measure import entity_id

PARTIAL_RECEIPT_PREFIX = 'PRC-'
ALIGNED = 'aligned'
NO_COMMON_REGISTRATION = 'no_common_registration'


def canonical_archive(archive: dict) -> str:
    return json.dumps(archive, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


class PartialReportStore:
    def __init__(self, connection):
        self.connection = connection

    def initialize(self) -> None:
        with transaction(self.connection):
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS partial_reports (
                    id INTEGER PRIMARY KEY,
                    handoff_id TEXT NOT NULL,
                    snapshot TEXT NOT NULL
                )
            ''')
            self.connection.execute('''
                CREATE TABLE IF NOT EXISTS partial_receipts (
                    report_id INTEGER PRIMARY KEY REFERENCES partial_reports(id),
                    receipt_id TEXT NOT NULL UNIQUE
                )
            ''')

    def commit_partial(self, archive: dict) -> dict:
        """Write report and receipt in one transaction; failure leaves nothing."""
        report_id = archive['report_id']
        receipt_id = archive['receipt']['id']
        snapshot = canonical_archive(archive)
        with transaction(self.connection):
            self.connection.execute(
                'INSERT INTO partial_reports (id, handoff_id, snapshot) VALUES (?, ?, ?)',
                (report_id, archive['handoff_id'], snapshot),
            )
            self.connection.execute(
                'INSERT INTO partial_receipts (report_id, receipt_id) VALUES (?, ?)',
                (report_id, receipt_id),
            )
        return json.loads(snapshot)

    def next_report_id(self) -> int:
        row = self.connection.execute(
            'SELECT COALESCE(MAX(id), 0) + 1 FROM partial_reports'
        ).fetchone()
        return row[0]

    def read_partial(self, report_id: int) -> dict:
        report_id = entity_id(report_id, 'report number')
        row = self.connection.execute('''
            SELECT report.snapshot, receipt.receipt_id
            FROM partial_reports AS report
            JOIN partial_receipts AS receipt ON receipt.report_id = report.id
            WHERE report.id = ?
        ''', (report_id,)).fetchone()
        if row is None:
            raise LookupError(f'unknown partial report {report_id}')
        snapshot, receipt_id = row
        archive = json.loads(snapshot)
        if archive['receipt']['id'] != receipt_id or archive['receipt']['report_id'] != report_id:
            raise ValueError('stored partial receipt does not match its report')
        return archive


def make_partial_receipt(report_id: int) -> dict:
    return {'id': f'{PARTIAL_RECEIPT_PREFIX}{report_id}', 'report_id': report_id}
