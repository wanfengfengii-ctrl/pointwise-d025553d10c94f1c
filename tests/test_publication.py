from dataclasses import replace
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest

from analysis.execute import evaluate
from database import open_database
from demo import issue_sample, load_sample
from report.history import get
from report.publication import publish
from report.store import ReportStore
from review.intake import order
from review.store import OrderStore
from survey.store import ObservationStore


def counts(connection):
    return connection.execute('''
        SELECT (SELECT count(*) FROM reports), (SELECT count(*) FROM receipts)
    ''').fetchone()


class PublicationTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.path = root / 'center.sqlite'
        sample = load_sample('rotated')
        with open_database(root / 'station.sqlite') as connection:
            observations = ObservationStore(connection)
            observations.initialize()
            _, self.pieces = issue_sample(observations, sample)
        with open_database(self.path) as connection:
            orders = OrderStore(connection)
            orders.initialize()
            ReportStore(connection).initialize()
            fixed = order(orders, self.pieces, sample['probes'])
            self.outcome = evaluate(fixed, self.pieces)

    def test_commit_failure(self):
        with open_database(self.path) as connection:
            connection.executescript('''
                CREATE TABLE permitted_receipts (id INTEGER PRIMARY KEY);
                CREATE TABLE commit_guard (
                    receipt INTEGER REFERENCES permitted_receipts(id)
                            DEFERRABLE INITIALLY DEFERRED
                );
                CREATE TRIGGER fail_receipt_commit AFTER INSERT ON receipts
                BEGIN
                    INSERT INTO commit_guard(receipt) VALUES (NEW.report_id);
                END;
            ''')
            with self.assertRaisesRegex(sqlite3.IntegrityError, 'FOREIGN KEY constraint failed'):
                publish(ReportStore(connection), self.outcome)
            self.assertFalse(connection.in_transaction)
            self.assertEqual(counts(connection), (0, 0))
            self.assertEqual(connection.execute('SELECT count(*) FROM commit_guard').fetchone(), (0,))
        with open_database(self.path) as connection:
            self.assertEqual(counts(connection), (0, 0))
            self.assertEqual(connection.execute('SELECT count(*) FROM review_orders').fetchone(), (1,))
            connection.execute('DROP TRIGGER fail_receipt_commit')
            orders = OrderStore(connection)
            reports = ReportStore(connection)
            fixed = orders.read_order(self.outcome.order_id)
            result = publish(reports, evaluate(fixed, self.pieces))
            self.assertEqual(counts(connection), (1, 1))
            self.assertEqual(result.receipt.report_id, result.id)
            self.assertEqual(result.receipt.order_id, fixed.id)
            self.assertEqual(result.outcome, self.outcome)
        with open_database(self.path) as connection:
            self.assertEqual(get(ReportStore(connection), result.id), result)

    def test_rejects_outcome_of_different_bound_points(self):
        with open_database(self.path) as connection:
            second = order(OrderStore(connection), self.pieces, {'B': [1, 0], 'C': [0, 0]})
            wrong_order = replace(self.outcome, order_id=second.id)
            with self.assertRaisesRegex(ValueError, 'persisted review order'):
                publish(ReportStore(connection), wrong_order)
            self.assertEqual(counts(connection), (0, 0))

    def test_rejects_outcome_of_different_bound_pieces(self):
        with open_database(':memory:') as station:
            observations = ObservationStore(station)
            observations.initialize()
            sample = load_sample('rotated')
            issue_sample(observations, sample)
            _, later = issue_sample(observations, sample)
        with open_database(self.path) as connection:
            second = order(OrderStore(connection), later, {'B': [0, 0], 'C': [0, 0]})
            self.assertEqual(evaluate(second, later).pairs, self.outcome.pairs)
            with self.assertRaisesRegex(ValueError, 'persisted review order'):
                publish(ReportStore(connection), replace(self.outcome, order_id=second.id))
            self.assertEqual(counts(connection), (0, 0))
