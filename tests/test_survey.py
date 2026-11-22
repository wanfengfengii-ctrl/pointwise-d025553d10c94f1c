from contextlib import ExitStack
from fractions import Fraction
import unittest

from database import open_database
from overlap.issue import freeze
from survey.corrections import amend
from survey.intake import record
from survey.revisions import get_revision
from survey.store import ObservationStore

BASE = [{'category': 'red', 'point': [0, 0]}, {'category': 'blue', 'point': [2, 0]}]


class SurveyTests(unittest.TestCase):
    def setUp(self):
        stack = self.enterContext(ExitStack())
        self.connection = stack.enter_context(open_database(':memory:'))
        self.store = ObservationStore(self.connection)
        self.store.initialize()
        self.original_id = record(self.store, 'batch', 'A', BASE)
        self.original = get_revision(self.store, self.original_id)

    def assert_original_only(self):
        ids = self.connection.execute('SELECT id FROM observation_revisions').fetchall()
        self.assertEqual(ids, [(self.original_id,)])
        self.assertEqual(get_revision(self.store, self.original_id), self.original)
        self.assertEqual(self.connection.execute('SELECT count(*) FROM observation_markers').fetchone(), (2,))

    def test_duplicate_marker_position(self):
        duplicate = [{'category': 'red', 'point': [0, 0]}, {'category': 'red', 'point': [0, 0]}]
        with self.assertRaisesRegex(ValueError, 'duplicate marker position'):
            record(self.store, 'batch', 'A', duplicate)
        self.assert_original_only()

    def test_rational_alias(self):
        duplicate = [
            {'category': 'red', 'point': ['1/2', 0]},
            {'category': 'blue', 'point': ['2/4', '0/3']},
        ]
        with self.assertRaisesRegex(ValueError, 'duplicate marker position'):
            record(self.store, 'batch', 'A', duplicate)
        self.assert_original_only()
        b = record(self.store, 'batch', 'B', BASE)
        self.assertEqual(len(freeze(self.store, 'AB', b, self.original_id).transforms), 1)

    def test_invalid_marker_input(self):
        invalid_tables = [
            [BASE[0], {'point': [2, 0]}],
            [BASE[0], {'category': '', 'point': [2, 0]}],
            [BASE[0], {'category': 'blue', 'point': ['1/0', 0]}],
            [BASE[0], {'category': 'blue', 'point': [0.5, 0]}],
            [BASE[0], {'category': 'blue', 'point': [True, 0]}],
            [BASE[0]],
        ]
        for rows in invalid_tables:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                record(self.store, 'batch', 'A', rows)
        for batch, station in [('', 'A'), ('batch', 'D')]:
            with self.subTest(batch=batch, station=station), self.assertRaises(ValueError):
                record(self.store, batch, station, BASE)
        self.assert_original_only()

    def test_rejected_amendment(self):
        replacement = [{'at': [2, 0], 'category': 'blue', 'point': [0, 0]}]
        with self.assertRaises(LookupError):
            amend(self.store, self.original_id + 100, replacement)
        with self.assertRaisesRegex(ValueError, 'duplicate marker position'):
            amend(self.store, self.original_id, replacement)
        with self.assertRaisesRegex(ValueError, 'existing marker position'):
            amend(self.store, self.original_id, [{'at': [4, 0], 'category': 'blue', 'point': [1, 0]}])
        self.assert_original_only()
        b = record(self.store, 'batch', 'B', BASE)
        transform, = freeze(self.store, 'AB', b, self.original_id).transforms
        self.assertEqual(transform.apply((0, 0)), (0, 0))

    def test_simultaneous_correction_keeps_original(self):
        changed = amend(self.store, self.original_id, [
            {'at': [0, 0], 'category': 'red', 'point': [2, 0]},
            {'at': [2, 0], 'category': 'blue', 'point': ['0/5', 0]},
        ])
        self.assertNotEqual(changed, self.original_id)
        corrected = get_revision(self.store, changed)
        self.assertEqual((corrected.batch, corrected.station, corrected.parent_id), ('batch', 'A', self.original_id))
        self.assertEqual(corrected.markers.by_category(), {'red': {(Fraction(2), Fraction(0))}, 'blue': {(Fraction(0), Fraction(0))}})
        self.assertEqual(get_revision(self.store, self.original_id), self.original)
