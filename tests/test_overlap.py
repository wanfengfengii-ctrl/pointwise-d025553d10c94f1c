from fractions import Fraction as F
import json
import unittest

from database import open_database
from overlap.exchange import export_evidence, verify_evidence
from overlap.issue import freeze
from survey.intake import record
from survey.store import ObservationStore


def markers(*rows):
    return [{'category': category, 'point': [x, y]} for category, x, y in rows]


def transform_fields(transform):
    return transform.c, transform.s, transform.tx, transform.ty


class OverlapTests(unittest.TestCase):
    def setUp(self):
        self.connection = self.enterContext(open_database(':memory:'))
        self.store = ObservationStore(self.connection)
        self.store.initialize()

    def issue(self, source, target):
        b = record(self.store, 'batch', 'B', source)
        a = record(self.store, 'batch', 'A', target)
        return freeze(self.store, 'AB', b, a)

    def test_unique_pose(self):
        source = markers(('red', 0, 0), ('blue', 2, 0))
        target = markers(('red', '1/2', 1), ('blue', '1/2', 3))
        with open_database(':memory:') as connection:
            store = ObservationStore(connection)
            store.initialize()
            b = record(store, 'batch', 'B', source)
            a = record(store, 'batch', 'A', target)
            serialized = export_evidence(freeze(store, 'AB', b, a))
        wire = json.loads(serialized)
        self.assertEqual(set(wire), {'version', 'ref', 'body'})
        self.assertEqual(wire['body'], {'transforms': [['0', '1', '1/2', '1']]})
        self.assertNotIn('red', serialized)
        self.assertNotIn('blue', serialized)
        decoded = verify_evidence(serialized)
        self.assertEqual((decoded.ref.source_station, decoded.ref.source_revision), ('B', b))
        self.assertEqual((decoded.ref.target_station, decoded.ref.target_revision), ('A', a))
        pose, = decoded.transforms
        self.assertEqual(transform_fields(pose), (0, 1, F(1, 2), 1))
        self.assertEqual(pose.apply((1, 0)), (F(1, 2), 2))

    def test_class_sets(self):
        source = markers(('a', 0, 0), ('b', 2, 0), ('c', 0, 1))
        with self.subTest('all classes fit'):
            target = markers(('a', 1, 1), ('b', 3, 1), ('c', 1, 2))
            pose, = self.issue(source, target).transforms
            self.assertEqual(transform_fields(pose), (1, 0, 1, 1))
        with self.subTest('anchors fit a reflection only'):
            reflected = markers(('a', 1, 1), ('b', 3, 1), ('c', 1, 0))
            self.assertEqual(self.issue(source, reflected).transforms, ())
        with self.subTest('unmatched class'):
            other = markers(('a', 1, 1), ('b', 3, 1), ('x', 1, 2))
            self.assertEqual(self.issue(source, other).transforms, ())

    def test_symmetric_candidates(self):
        identical = markers(('rim', -1, 0), ('rim', 1, 0))
        restored = verify_evidence(export_evidence(self.issue(identical, identical)))
        self.assertEqual(tuple(map(transform_fields, restored.transforms)), ((-1, 0, 0, 0), (1, 0, 0, 0)))

    def test_empty_evidence(self):
        source = markers(('red', 0, 0), ('blue', 1, 0))
        target = markers(('red', 0, 0), ('blue', 2, 0))
        piece = self.issue(source, target)
        text = export_evidence(piece)
        self.assertEqual(json.loads(text)['body'], {'transforms': []})
        self.assertEqual(verify_evidence(text), piece)
        self.assertEqual(piece.transforms, ())

    def test_canonical_exchange(self):
        source = markers(('red', '1/2', 0), ('blue', 2, 0))
        same = markers(('blue', '8/4', '0/4'), ('red', '2/4', 0))
        first = self.issue(source, source)
        second = self.issue(same, same)
        wire_first = json.loads(export_evidence(first))
        wire_second = json.loads(export_evidence(second))
        self.assertEqual(wire_first['body'], wire_second['body'])
        self.assertEqual(first.ref.body_sha256, second.ref.body_sha256)
        self.assertNotEqual(first.ref.id, second.ref.id)
        repeated = freeze(self.store, 'AB', first.ref.source_revision, first.ref.target_revision)
        self.assertEqual(export_evidence(first), export_evidence(repeated))
        self.assertEqual(verify_evidence(json.dumps(wire_first, indent=2)), first)

    def test_exchange_rejects_altered_content_and_source(self):
        source = markers(('red', 0, 0), ('blue', 2, 0))
        text = export_evidence(self.issue(source, source))
        altered_body = json.loads(text)
        altered_body['body']['transforms'][0][2] = '1'
        with self.assertRaisesRegex(ValueError, 'checksum'):
            verify_evidence(json.dumps(altered_body))
        altered_ref = json.loads(text)
        altered_ref['ref']['source_revision'] += 1000
        with self.assertRaisesRegex(ValueError, 'identity'):
            verify_evidence(json.dumps(altered_ref))
        with self.assertRaisesRegex(ValueError, 'duplicate evidence JSON member'):
            verify_evidence(text.replace('"version":1', '"version":1,"version":1'))

    def test_freeze_validates_revision_batch_and_direction(self):
        base = markers(('red', 0, 0), ('blue', 2, 0))
        a = record(self.store, 'batch', 'A', base)
        b = record(self.store, 'batch', 'B', base)
        other_b = record(self.store, 'other', 'B', base)
        with self.assertRaisesRegex(ValueError, 'direction'):
            freeze(self.store, 'AB', a, b)
        with self.assertRaisesRegex(ValueError, 'same batch'):
            freeze(self.store, 'AB', other_b, a)
        with self.assertRaises(LookupError):
            freeze(self.store, 'AB', b + 1000, a)
