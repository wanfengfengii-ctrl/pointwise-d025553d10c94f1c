import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from analysis.execute import evaluate
from database import open_database
from demo import issue_sample, issue_selection, load_sample
from overlap.exchange import verify_evidence
from overlap.issue import freeze
from report.export import export_report
from report.history import get
from report.publication import publish
from report.store import ReportStore
from review.intake import order
from review.store import OrderStore
from survey.corrections import amend
from survey.revisions import get_revision
from survey.store import ObservationStore


class HistoryTests(unittest.TestCase):
    def setUp(self):
        directory = Path(self.enterContext(TemporaryDirectory()))
        self.station_path = directory / 'station.sqlite'
        self.center_path = directory / 'center.sqlite'
        self.sample = load_sample('rotated')
        with open_database(self.station_path) as connection:
            store = ObservationStore(connection)
            store.initialize()
            self.revisions, self.original_pieces = issue_sample(store, self.sample)
        with open_database(self.center_path) as connection:
            OrderStore(connection).initialize()
            ReportStore(connection).initialize()

    def corrected_pieces(self):
        correction = self.sample['correction']
        key = correction['observation']
        with open_database(self.station_path) as connection:
            store = ObservationStore(connection)
            new_id = amend(store, self.revisions[key], correction['replacements'])
            selected = {**self.revisions, key: new_id}
            return new_id, issue_selection(store, self.sample['edges'], selected)

    def sign(self, pieces):
        with open_database(self.center_path) as connection:
            orders = OrderStore(connection)
            reports = ReportStore(connection)
            fixed = order(orders, pieces, self.sample['probes'])
            return fixed, publish(reports, evaluate(orders.read_order(fixed.id), pieces))

    def test_amend_then_reopen(self):
        fixed, original = self.sign(self.original_pieces)
        with open_database(self.center_path) as connection:
            original_text = export_report(ReportStore(connection), original.id)
        new_id, corrected_pieces = self.corrected_pieces()
        _, original_after_correction = self.sign(self.original_pieces)
        fixed_new, corrected = self.sign(corrected_pieces)
        self.assertEqual(original_after_correction.outcome.references, original.outcome.references)
        self.assertEqual(original_after_correction.outcome.pairs, (((1, 0), (1, 1)),))
        self.assertEqual(corrected.outcome.pairs, (((2, 0), (2, 1)),))
        self.assertEqual([ref.target_revision for ref in corrected.outcome.references[:2]], [new_id, new_id])
        self.assertEqual(corrected.outcome.references[2], original.outcome.references[2])
        self.station_path.unlink()
        with open_database(self.center_path) as connection:
            orders = OrderStore(connection)
            reports = ReportStore(connection)
            self.assertEqual(orders.read_order(fixed.id), fixed)
            self.assertEqual(orders.read_order(fixed_new.id), fixed_new)
            self.assertEqual(get(reports, original.id), original)
            self.assertEqual(get(reports, corrected.id), corrected)
            self.assertEqual(export_report(reports, original.id), original_text)
            exported = json.loads(export_report(reports, corrected.id))
            self.assertEqual(exported['pairs'], [[['2', '0'], ['2', '1']]])
            self.assertEqual(exported['references'], [verify_evidence(text).ref.to_dict() for text in corrected_pieces])
            self.assertEqual(exported['receipt'], {'id': f'RCP-{corrected.id}', 'order_id': fixed_new.id, 'report_id': corrected.id})
        self.assertFalse(self.station_path.exists())

    def test_revision_lineage(self):
        old_id = self.revisions['a']
        with open_database(self.station_path) as connection:
            store = ObservationStore(connection)
            old = get_revision(store, old_id)
            new_id = amend(store, old_id, [{'at': [1, 2], 'category': 'blue', 'point': [1, 3]}])
        with open_database(self.station_path) as connection:
            store = ObservationStore(connection)
            self.assertEqual(get_revision(store, old_id), old)
            revised = get_revision(store, new_id)
            self.assertEqual((revised.batch, revised.station, revised.parent_id), (old.batch, old.station, old_id))
            self.assertEqual(revised.markers.by_category(), {'red': {(1, 0)}, 'blue': {(1, 3)}})
            old_piece = freeze(store, 'AB', self.revisions['b'], old_id)
            new_piece = freeze(store, 'AB', self.revisions['b'], new_id)
        self.assertEqual(old_piece, verify_evidence(self.original_pieces[0]))
        self.assertEqual(new_piece.ref.target_revision, new_id)
        self.assertEqual(new_piece.transforms, ())
        self.assertNotEqual(new_piece.ref.id, old_piece.ref.id)

    def test_receipt_identity(self):
        fixed, original = self.sign(self.original_pieces)
        _, corrected_pieces = self.corrected_pieces()
        fixed_new, corrected = self.sign(corrected_pieces)
        with open_database(self.center_path) as connection:
            store = ReportStore(connection)
            for report, review in ((corrected, fixed_new), (original, fixed), (corrected, fixed_new)):
                with self.subTest(report=report.id):
                    retrieved = get(store, report.id)
                    self.assertEqual(retrieved, report)
                    self.assertEqual(retrieved.outcome.references, review.references)
                    self.assertEqual(retrieved.receipt.id, f'RCP-{report.id}')
                    self.assertEqual(retrieved.receipt.order_id, review.id)
                    self.assertEqual(retrieved.receipt.report_id, report.id)
        self.assertNotEqual(original.receipt.id, corrected.receipt.id)

    def test_unknown_report(self):
        _, original = self.sign(self.original_pieces)
        with open_database(self.center_path) as connection:
            store = ReportStore(connection)
            for read in (get, export_report):
                with self.subTest(read=read.__name__), self.assertRaisesRegex(LookupError, 'unknown report'):
                    read(store, original.id + 100)
            self.assertEqual(get(store, original.id), original)

    def test_repeat_initialize_preserves_records(self):
        fixed, original = self.sign(self.original_pieces)
        new_id, corrected_pieces = self.corrected_pieces()
        fixed_new, corrected = self.sign(corrected_pieces)
        with open_database(self.station_path) as connection:
            observations = ObservationStore(connection)
            ids = (*self.revisions.values(), new_id)
            before = tuple(get_revision(observations, number) for number in ids)
            count_before = connection.execute('SELECT count(*) FROM observation_markers').fetchone()
            observations.initialize()
            observations.initialize()
            self.assertEqual(tuple(get_revision(observations, number) for number in ids), before)
            self.assertEqual(connection.execute('SELECT count(*) FROM observation_revisions').fetchone(), (4,))
            self.assertEqual(connection.execute('SELECT count(*) FROM observation_markers').fetchone(), count_before)
        with open_database(self.center_path) as connection:
            orders = OrderStore(connection)
            reports = ReportStore(connection)
            order_numbers = [fixed.id, fixed_new.id]
            report_numbers = [original.id, corrected.id]
            exported = [export_report(reports, number) for number in report_numbers]
            for _ in range(2):
                orders.initialize()
                reports.initialize()
            self.assertEqual([orders.read_order(number) for number in order_numbers], [fixed, fixed_new])
            self.assertEqual([get(reports, number) for number in report_numbers], [original, corrected])
            self.assertEqual([export_report(reports, number) for number in report_numbers], exported)
            self.assertEqual(connection.execute('''
                SELECT (SELECT count(*) FROM review_orders), (SELECT count(*) FROM reports),
                       (SELECT count(*) FROM receipts)
            ''').fetchone(), (2, 2, 2))
