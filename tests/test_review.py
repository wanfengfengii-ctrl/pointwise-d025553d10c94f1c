from fractions import Fraction as F
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from analysis.alignment import find_joint_poses
from analysis.execute import evaluate
from database import open_database
from demo import issue_sample, load_sample
from overlap.exchange import export_evidence, verify_evidence
from overlap.issue import freeze
from report.history import get
from report.publication import publish
from report.store import ReportStore
from review.intake import order
from review.received import receive_pieces
from review.store import OrderStore
from survey.corrections import amend
from survey.intake import record
from survey.store import ObservationStore

ORIGINS = {'B': [0, 0], 'C': [0, 0]}


class ReviewTests(unittest.TestCase):
    def setUp(self):
        root = Path(self.enterContext(TemporaryDirectory()))
        self.station_path = root / 'station.sqlite'
        self.connection = self.enterContext(open_database(root / 'center.sqlite'))
        self.orders = OrderStore(self.connection)
        self.reports = ReportStore(self.connection)
        self.orders.initialize()
        self.reports.initialize()

    def pieces(self, case):
        with open_database(self.station_path) as connection:
            store = ObservationStore(connection)
            store.initialize()
            _, pieces = issue_sample(store, load_sample(case))
        return pieces

    def counts(self):
        return self.connection.execute('''
            SELECT (SELECT count(*) FROM review_orders), (SELECT count(*) FROM reports),
                   (SELECT count(*) FROM receipts)
        ''').fetchone()

    def conclude(self, pieces, probes):
        fixed = order(self.orders, pieces, probes)
        outcome = evaluate(self.orders.read_order(fixed.id), pieces)
        published = publish(self.reports, outcome)
        self.assertEqual(get(self.reports, published.id), published)
        return fixed, published

    def test_offline_rotated_overlap(self):
        pieces = self.pieces('rotated')
        self.station_path.unlink()
        fixed, report = self.conclude(pieces[::-1], ORIGINS)
        self.assertEqual(report.outcome.status, 'aligned')
        self.assertEqual(report.outcome.pairs, (((1, 0), (1, 1)),))
        expected_references = tuple(json.loads(text)['ref'] for text in pieces)
        self.assertEqual(tuple(ref.to_dict() for ref in fixed.references), expected_references)
        self.assertEqual(report.outcome.references, fixed.references)
        self.assertEqual(report.receipt.order_id, fixed.id)
        self.assertEqual(report.receipt.report_id, report.id)
        self.assertFalse(self.station_path.exists())

    def test_composition_order(self):
        pieces = self.pieces('rotated')
        ab, ac, bc = [verify_evidence(text).transforms[0] for text in pieces]
        self.assertEqual((ab.c, ab.s, ab.tx, ab.ty), (0, 1, 1, 0))
        self.assertEqual((bc.c, bc.s, bc.tx, bc.ty), (1, 0, 1, 0))
        self.assertEqual((ac.c, ac.s, ac.tx, ac.ty), (0, 1, 1, 1))
        self.assertEqual(ab.compose(bc).apply((0, 0)), (1, 1))
        self.assertEqual(bc.compose(ab).apply((0, 0)), (2, 0))
        _, report = self.conclude(pieces, ORIGINS)
        self.assertEqual(report.outcome.pairs, (((1, 0), (1, 1)),))

    def test_rational_result(self):
        pieces = self.pieces('rotated')
        fixed, report = self.conclude(pieces, {'C': ['1/3', 0], 'B': ['1/2', 0]})
        self.assertEqual(report.outcome.pairs, (((F(1), F(1, 2)), (F(1), F(4, 3))),))
        self.assertIsInstance(report.outcome.pairs[0][1][1], F)
        self.assertEqual(report.outcome.points, fixed.points)
        self.assertEqual(report.outcome.references, tuple(verify_evidence(text).ref for text in pieces))

    def test_bound_body(self):
        sample = load_sample('rotated')
        with open_database(self.station_path) as connection:
            store = ObservationStore(connection)
            store.initialize()
            revisions, pieces = issue_sample(store, sample)
            updated = amend(store, revisions['a'], sample['correction']['replacements'])
            replacement = export_evidence(freeze(store, 'AB', revisions['b'], updated))
        alternate = verify_evidence(replacement)
        on_file = verify_evidence(pieces[0])
        self.assertEqual((alternate.ref.batch, alternate.ref.role), (on_file.ref.batch, on_file.ref.role))
        self.assertNotEqual(alternate.ref.target_revision, on_file.ref.target_revision)
        self.assertNotEqual(alternate.transforms, on_file.transforms)
        fixed = order(self.orders, pieces, ORIGINS)
        persisted = self.orders.read_order(fixed.id)
        self.station_path.unlink()
        with self.assertRaisesRegex(ValueError, 'fixed order'):
            evaluate(persisted, (replacement, *pieces[1:]))
        self.assertEqual(self.counts(), (1, 0, 0))
        self.assertEqual(evaluate(persisted, pieces).pairs, (((1, 0), (1, 1)),))
        self.assertEqual(self.orders.read_order(fixed.id), fixed)

    def test_other_batch(self):
        sample = load_sample('rotated')
        with open_database(self.station_path) as connection:
            store = ObservationStore(connection)
            store.initialize()
            _, originals = issue_sample(store, sample)
            _, elsewhere = issue_sample(store, {**sample, 'batch': 'other-batch'})
        self.assertEqual(verify_evidence(originals[2]).transforms, verify_evidence(elsewhere[2]).transforms)
        with self.assertRaisesRegex(ValueError, 'single batch'):
            order(self.orders, (*originals[:2], elsewhere[2]), ORIGINS)
        self.assertEqual(self.counts(), (0, 0, 0))
        self.assertEqual(order(self.orders, originals, ORIGINS).batch, sample['batch'])
        self.assertEqual(self.counts(), (1, 0, 0))

    def test_wrong_direction(self):
        pieces = self.pieces('rotated')
        backwards = json.loads(pieces[2])
        ref = backwards['ref']
        ref['source_station'], ref['target_station'] = ref['target_station'], ref['source_station']
        ref['source_revision'], ref['target_revision'] = ref['target_revision'], ref['source_revision']
        with self.assertRaisesRegex(ValueError, 'direction'):
            order(self.orders, (*pieces[:2], json.dumps(backwards)), ORIGINS)
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_missing_or_duplicate_role(self):
        ab, ac, _ = self.pieces('rotated')
        with self.assertRaisesRegex(ValueError, 'AB, AC and BC'):
            order(self.orders, (ab, ac), ORIGINS)
        with self.assertRaisesRegex(ValueError, 'duplicate evidence role'):
            order(self.orders, (ab, ac, ac), ORIGINS)
        self.assertEqual(self.counts(), (0, 0, 0))

    def test_wrong_point_station(self):
        pieces = self.pieces('rotated')
        for probes in ({'B': [0, 0], 'A': [0, 0]}, {'B': [0, 0]}, {'B': [0, 0], 'C': [0, 0], 'A': [0, 0]}):
            with self.subTest(probes=probes), self.assertRaisesRegex(ValueError, 'one point for B and one for C'):
                order(self.orders, pieces, probes)
        self.assertEqual(self.counts(), (0, 0, 0))

    def inconsistent_pieces(self):
        with open_database(self.station_path) as connection:
            store = ObservationStore(connection)
            store.initialize()
            revisions, pieces = issue_sample(store, load_sample('symmetric'))
            distinct = [{'category': 'left', 'point': [-1, 0]}, {'category': 'right', 'point': [1, 0]}]
            a = record(store, 'contour-half-turn', 'A', distinct)
            c = record(store, 'contour-half-turn', 'C', distinct)
            return (
                export_evidence(freeze(store, 'AB', revisions['b_marked'], a)),
                export_evidence(freeze(store, 'AC', c, a)),
                pieces[2],
            )

    def test_inconsistent_cycle(self):
        pieces = self.inconsistent_pieces()
        self.assertEqual([verify_evidence(text).transforms[0].c for text in pieces], [1, 1, -1])
        _, report = self.conclude(pieces, {'B': [1, 0], 'C': [1, 0]})
        self.assertEqual(report.outcome.status, 'no_common_registration')
        self.assertEqual(report.outcome.pairs, ())
        self.assertEqual(len(report.outcome.references), 3)

    def test_origin_conflict(self):
        pieces = self.inconsistent_pieces()
        self.assertEqual([verify_evidence(text).transforms[0].apply((0, 0)) for text in pieces], [(0, 0)] * 3)
        _, report = self.conclude(pieces, ORIGINS)
        self.assertEqual((report.outcome.status, report.outcome.pairs), ('no_common_registration', ()))

    def test_empty_edge(self):
        sample = load_sample('rotated')
        with open_database(self.station_path) as connection:
            store = ObservationStore(connection)
            store.initialize()
            revisions, pieces = issue_sample(store, sample)
            longer = amend(store, revisions['b'], [{'at': [2, 0], 'category': 'blue', 'point': [3, 0]}])
            empty = export_evidence(freeze(store, 'AB', longer, revisions['a']))
        self.assertEqual(verify_evidence(empty).transforms, ())
        _, report = self.conclude((empty, *pieces[1:]), ORIGINS)
        self.assertEqual((report.outcome.status, report.outcome.pairs), ('no_common_registration', ()))
        self.assertEqual(report.outcome.references[0], verify_evidence(empty).ref)

    def test_symmetric_markers(self):
        pieces = self.pieces('symmetric')
        self.station_path.unlink()
        _, report = self.conclude(pieces, {'B': [1, 0], 'C': [1, 0]})
        self.assertEqual(report.outcome.status, 'aligned')
        self.assertEqual(report.outcome.pairs, (((-1, 0), (1, 0)), ((1, 0), (-1, 0))), 'JOINT_POSE_MISMATCH')
        self.assertEqual(tuple(ref.role for ref in report.outcome.references), ('AB', 'AC', 'BC'))

    def test_coincident_projection(self):
        pieces = self.pieces('symmetric')
        witnesses = tuple(find_joint_poses(receive_pieces(pieces)))
        self.assertEqual({(pose.b_to_a.c, pose.c_to_a.c) for pose in witnesses}, {(-1, 1), (1, -1)})
        self.assertEqual(len(witnesses), 2)
        _, report = self.conclude(pieces, ORIGINS)
        self.assertEqual(report.outcome.status, 'aligned')
        self.assertEqual(report.outcome.pairs, (((0, 0), (0, 0)),))
