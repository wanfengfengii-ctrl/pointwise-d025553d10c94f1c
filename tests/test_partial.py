import json
import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from database import open_database
from overlap.issue import (
    export_partial_links, freeze_partial, open_partial,
)
from overlap.partial_link import verify_partial_links
from overlap.partial_piece import verify_partial_piece
from report.export import export_partial
from report.history import get_partial
from report.partial_store import PartialReportStore
from report.publication import publish_partial
from report.store import ReportStore
from survey.corrections import amend
from survey.intake import record
from survey.store import ObservationStore

from partial_cases import CASE_MARKERS, PROBES, record_case, ROLES, ZERO_PROBES


def issue_all(store, revisions):
    handoff = open_partial(store, revisions)
    texts = tuple(freeze_partial(store, handoff, role) for role in ROLES)
    links = export_partial_links(store, handoff, texts)
    return handoff, texts, links


class PartialHandoffTests(unittest.TestCase):
    def setUp(self):
        self.connection = self.enterContext(open_database(':memory:'))
        self.store = ObservationStore(self.connection)
        self.store.initialize()
        self.revisions = record_case(self.store, 'two_common')

    def test_open_requires_three_stations_and_one_batch(self):
        with self.assertRaises(ValueError):
            open_partial(self.store, {'A': self.revisions['A'], 'B': self.revisions['B']})
        other = record_case(self.store, 'one_common')
        mixed = {**self.revisions, 'C': other['C']}
        with self.assertRaises(ValueError):
            open_partial(self.store, mixed)

    def test_each_opening_is_isolated_even_for_same_revisions(self):
        first = open_partial(self.store, self.revisions)
        second = open_partial(self.store, self.revisions)
        self.assertNotEqual(first.handoff_id, second.handoff_id)
        first_piece = freeze_partial(self.store, first, 'AB')
        second_piece = freeze_partial(self.store, second, 'AB')
        self.assertFalse(_endpoints(first_piece) & _endpoints(second_piece))
        # The same A-station record receives the same endpoint name on both
        # edges (AB and AC) of the same handoff.
        ab_text = freeze_partial(self.store, first, 'AB')
        ac_text = freeze_partial(self.store, first, 'AC')
        a_endpoints_ab = {name for name in _endpoints(ab_text) if '-A' in name}
        a_endpoints_ac = {name for name in _endpoints(ac_text) if '-A' in name}
        self.assertTrue(a_endpoints_ab and a_endpoints_ab <= a_endpoints_ac)

    def test_unknown_revision_is_lookup_error(self):
        with self.assertRaises(LookupError):
            open_partial(self.store, {**self.revisions, 'A': 999})

    def test_wrong_station_revision_rejected(self):
        swapped = {'A': self.revisions['B'], 'B': self.revisions['A'],
                   'C': self.revisions['C']}
        with self.assertRaises(ValueError):
            open_partial(self.store, swapped)

    def test_freeze_checks_handle_and_role(self):
        handoff = open_partial(self.store, self.revisions)
        with self.assertRaises(ValueError):
            freeze_partial(self.store, object(), 'AB')
        with self.assertRaises(ValueError):
            freeze_partial(self.store, handoff, 'XY')
        # A handle not present in this store is a LookupError.
        foreign = type(handoff)('ph-0' * 16, handoff.batch, handoff.revisions)
        with self.assertRaises(LookupError):
            freeze_partial(self.store, foreign, 'AB')


def _endpoints(text):
    return {
        endpoint
        for candidate in json.loads(text)['body']['candidates']
        for match in candidate['matches']
        for endpoint in match
    }


class PartialPieceTests(unittest.TestCase):
    def setUp(self):
        self.connection = self.enterContext(open_database(':memory:'))
        self.store = ObservationStore(self.connection)
        self.store.initialize()
        self.revisions = record_case(self.store, 'two_common')
        self.handoff = open_partial(self.store, self.revisions)

    def test_piece_envelope_and_private_data_stay_at_station(self):
        text = freeze_partial(self.store, self.handoff, 'AB')
        document = json.loads(text)
        self.assertEqual(set(document), {
            'version', 'handoff_id', 'id', 'batch', 'role',
            'source_revision', 'target_revision', 'body_sha256', 'body',
        })
        self.assertEqual(document['version'], 2)
        self.assertTrue(document['id'].startswith('ov2-'))
        self.assertEqual(document['role'], 'AB')
        # No raw coordinates, categories or station-local marker keys leak.
        # Check category words as JSON string tokens so hex id substrings
        # (e.g. a hex digit "u" cannot occur, but avoid incidental matches).
        string_tokens = set(re.findall(r'"([^"]+)"', text))
        for category in ('a_only', 'b_only', 'c_only'):
            self.assertNotIn(category, string_tokens)
        for raw_coordinate in ('1/2',):
            self.assertNotIn(raw_coordinate, text)
        candidates = document['body']['candidates']
        self.assertEqual(len(candidates[0]['matches']), 2)
        # Canonical ordering of transforms and matches.
        self.assertEqual(candidates, json.loads(json.dumps(candidates, sort_keys=True)))

    def test_identity_binds_provenance_and_digest(self):
        text = freeze_partial(self.store, self.handoff, 'AB')
        verified = verify_partial_piece(text)
        self.assertEqual(verified.id, json.loads(text)['id'])
        tampered = json.loads(text)
        tampered['batch'] = 'other'
        with self.assertRaises(ValueError):
            verify_partial_piece(json.dumps(tampered))
        bad_body = json.loads(text)
        bad_body['body']['candidates'][0]['matches'].append(
            ['ep-x', 'ep-y'])
        with self.assertRaises(ValueError):
            verify_partial_piece(json.dumps(bad_body))

    def test_bad_envelopes_rejected(self):
        text = freeze_partial(self.store, self.handoff, 'AB')
        base = json.loads(text)
        for mutate in (
            lambda d: d.update(version=1),
            lambda d: d.update(role='AC'),
            lambda d: d.update(handoff_id='ph-other'),
            lambda d: d.update(body_sha256='0' * 64),
            lambda d: d.pop('id'),
        ):
            broken = json.loads(text)
            mutate(broken)
            with self.assertRaises((ValueError, KeyError)):
                verify_partial_piece(json.dumps(broken))
        with self.assertRaises(ValueError):
            verify_partial_piece('not json')
        self.assertFalse(base['id'] is None)

    def test_repeated_freeze_is_byte_identical(self):
        first = freeze_partial(self.store, self.handoff, 'BC')
        second = freeze_partial(self.store, self.handoff, 'BC')
        self.assertEqual(first, second)

    def test_duplicate_endpoint_in_candidate_rejected(self):
        text = freeze_partial(self.store, self.handoff, 'AB')
        broken = json.loads(text)
        first_match = broken['body']['candidates'][0]['matches'][0]
        broken['body']['candidates'][0]['matches'].append(
            [first_match[0], 'ep-other-A009'])
        broken['body']['candidates'][0]['matches'].sort()
        broken['body_sha256'] = _digest_of(broken['body'])
        broken['id'] = _recompute_id(broken)
        with self.assertRaises(ValueError):
            verify_partial_piece(json.dumps(broken))

    def test_noncanonical_candidate_order_rejected(self):
        text = freeze_partial(self.store, self.handoff, 'AB')
        document = json.loads(text)
        candidate = document['body']['candidates'][0]
        candidate['matches'] = list(reversed(candidate['matches']))
        document['body_sha256'] = _digest_of(document['body'])
        document['id'] = _recompute_id(document)
        with self.assertRaises(ValueError):
            verify_partial_piece(json.dumps(document))

    def test_candidate_needs_two_same_category_matches(self):
        # one_common's edges only keep the identity transform with two pairs.
        revisions = record_case(self.store, 'one_common')
        handoff = open_partial(self.store, revisions)
        for role in ROLES:
            text = freeze_partial(self.store, handoff, role)
            candidates = json.loads(text)['body']['candidates']
            self.assertEqual(len(candidates), 1)
            self.assertEqual(candidates[0]['transform'], ['1', '0', '0', '0'])
            self.assertGreaterEqual(len(candidates[0]['matches']), 2)


class PartialPublicationTests(unittest.TestCase):
    def setUp(self):
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.directory = Path(self._temp.name)
        self.station_path = self.directory / 'station.sqlite'
        self.center_path = self.directory / 'center.sqlite'
        with open_database(self.station_path) as connection:
            store = ObservationStore(connection)
            store.initialize()
            self.revisions = {
                name: record_case(store, name) for name in CASE_MARKERS
            }

    def _center(self):
        connection = self.enterContext(open_database(self.center_path))
        reports = ReportStore(connection)
        PartialReportStore(connection).initialize()
        return reports, connection

    def _issue(self, name):
        with open_database(self.station_path) as connection:
            store = ObservationStore(connection)
            return issue_all(store, self.revisions[name])

    def test_case_outcomes_match_hand_calculations(self):
        from partial_cases import EXPECTED
        reports, _ = self._center()
        for name, expected in EXPECTED.items():
            if name == 'half_turn_at_origin':
                continue
            _, pieces, links = self._issue(name)
            snapshot = publish_partial(reports, pieces[::-1], links, PROBES)
            self.assertEqual(snapshot['pairs'], expected)
            self.assertEqual(
                snapshot['status'], 'aligned' if expected else 'no_common_registration'
            )
            self.assertEqual(snapshot['references'],
                             [json.loads(text)['id'] for text in pieces])
            self.assertIsInstance(snapshot['report_id'], int)
            self.assertEqual(snapshot['receipt'],
                             {'id': f"PRC-{snapshot['report_id']}",
                              'report_id': snapshot['report_id']})

    def test_half_turn_origin_collapses_to_one_pair(self):
        reports, _ = self._center()
        _, pieces, links = self._issue('half_turn')
        snapshot = publish_partial(reports, pieces, links, ZERO_PROBES)
        self.assertEqual(snapshot['pairs'], [[['0', '0'], ['0', '0']]])

    def test_mixed_handoff_rejected_without_writing(self):
        reports, connection = self._center()
        _, original, links = self._issue('two_common')
        _, other, _ = self._issue('two_common')
        before = _count_reports(connection)
        with self.assertRaises(ValueError):
            publish_partial(reports, (other[0], *original[1:]), links, PROBES)
        self.assertEqual(_count_reports(connection), before)

    def test_bad_piece_and_bad_link_rejected(self):
        reports, connection = self._center()
        _, pieces, _ = self._issue('two_common')
        broken = json.loads(pieces[0])
        broken['body']['candidates'][0]['transform'][0] = '2'
        before = _count_reports(connection)
        with self.assertRaises(ValueError):
            publish_partial(reports, (json.dumps(broken), *pieces[1:]), (), PROBES)
        self.assertEqual(_count_reports(connection), before)
        with self.assertRaises(ValueError):
            publish_partial(reports, pieces, ('not-a-link',), PROBES)
        self.assertEqual(_count_reports(connection), before)

    def test_missing_role_and_illegal_points_rejected(self):
        reports, _ = self._center()
        _, pieces, links = self._issue('two_common')
        with self.assertRaises(ValueError):
            publish_partial(reports, pieces[:2], (), PROBES)
        with self.assertRaises(ValueError):
            publish_partial(reports, pieces, links, {'B': [0, 0]})
        with self.assertRaises(ValueError):
            publish_partial(reports, pieces, links, {'B': [0.5, 0], 'C': [0, 0]})

    def test_unknown_report_is_lookup_error(self):
        reports, _ = self._center()
        with self.assertRaises(LookupError):
            get_partial(reports, 4242)

    def test_failed_commit_leaves_no_rows_and_is_retryable(self):
        reports, connection = self._center()
        _, pieces, links = self._issue('two_common')
        original_execute = connection.execute

        class FlakyConnection:
            def __init__(self, inner):
                self._inner = inner
                self.armed = True

            def execute(self, sql, parameters=()):
                if self.armed and sql.lstrip().upper().startswith('INSERT INTO PARTIAL_RECEIPTS'):
                    raise RuntimeError('simulated commit failure')
                return self._inner.execute(sql, parameters)

            def __getattr__(self, name):
                return getattr(self._inner, name)

        flaky = FlakyConnection(connection)
        flaky_reports = ReportStore(flaky)
        with self.assertRaises(RuntimeError):
            publish_partial(flaky_reports, pieces, links, PROBES)
        flaky.armed = False
        self.assertEqual(_count_reports(connection), 0)
        snapshot = publish_partial(reports, pieces, links, PROBES)
        self.assertEqual(snapshot['report_id'], 1)
        self.assertEqual(get_partial(reports, 1), snapshot)
        self.assertEqual(json.loads(export_partial(reports, 1)), snapshot)

    def test_amendment_and_reopened_center_keep_old_archive(self):
        reports, _ = self._center()
        handoff, pieces, links = self._issue('two_common')
        snapshot = publish_partial(reports, pieces, links, PROBES)
        with open_database(self.station_path) as connection:
            store = ObservationStore(connection)
            amend(store, self.revisions['two_common']['A'], [
                {'at': [2, 0], 'category': 'v', 'point': [3, 0]},
            ])
        with open_database(self.center_path) as connection:
            reopened = ReportStore(connection)
            self.assertEqual(get_partial(reopened, snapshot['report_id']), snapshot)
            self.assertEqual(json.loads(export_partial(reopened, snapshot['report_id'])),
                             snapshot)

    def test_links_verify_equivalence_groups(self):
        _, pieces, links = self._issue('two_common')
        self.assertEqual(links, ())
        handoff_id = json.loads(pieces[0])['handoff_id']
        piece_ids = {json.loads(text)['id'] for text in pieces}
        self.assertEqual(verify_partial_links((), handoff_id, piece_ids), ())

    def test_renamed_endpoints_need_explicit_link_material(self):
        from overlap.partial_link import _encode_link
        reports, _ = self._center()
        _, pieces, _ = self._issue('two_common')
        renamed_texts, name_mapping = _rename_endpoints(pieces)
        # Without links the renamed edges cannot establish the two witness
        # triplets, so the publication must sign empty.
        empty = publish_partial(reports, renamed_texts, (), PROBES)
        self.assertEqual(empty['status'], 'no_common_registration')
        handoff_id = json.loads(pieces[0])['handoff_id']
        piece_ids = {json.loads(text)['id'] for text in renamed_texts}
        links = []
        for canonical_name, aliases in name_mapping.items():
            if len(aliases) < 2:
                continue
            body = {
                'groups': [[
                    [piece_ids_for(renamed_texts, alias), alias] for alias in aliases
                ]]
            }
            links.append(_encode_link(handoff_id, body))
        aligned = publish_partial(reports, renamed_texts, links, PROBES)
        self.assertEqual(aligned['status'], 'aligned')
        self.assertEqual(aligned['pairs'], [[['1', '0'], ['0', '1']]])
        self.assertEqual(len(aligned['link_references']), len(links))


def _count_reports(connection):
    return connection.execute('SELECT COUNT(*) FROM partial_reports').fetchone()[0]


def _digest_of(value):
    from hashlib import sha256
    canonical = json.dumps(value, ensure_ascii=True, sort_keys=True,
                           separators=(',', ':'))
    return sha256(canonical.encode('ascii')).hexdigest()


def _recompute_id(document):
    provenance = {
        'version': document['version'],
        'handoff_id': document['handoff_id'],
        'batch': document['batch'],
        'role': document['role'],
        'source_revision': document['source_revision'],
        'target_revision': document['target_revision'],
        'body_sha256': document['body_sha256'],
    }
    return 'ov2-' + _digest_of(provenance)


def _rename_endpoints(pieces):
    """Rebuild pieces with edge-local endpoint names plus provenance ids."""
    renamed = []
    mapping: dict[str, list[str]] = {}
    for index, text in enumerate(pieces):
        document = json.loads(text)
        local_names = {}

        def local_name(endpoint):
            if endpoint not in local_names:
                alias = f'edge{index}-{len(local_names):03d}'
                local_names[endpoint] = alias
                mapping.setdefault(endpoint, []).append(alias)
            return local_names[endpoint]

        for candidate in document['body']['candidates']:
            candidate['matches'] = sorted(
                [local_name(source), local_name(target)]
                for source, target in candidate['matches']
            )
        document['body_sha256'] = _digest_of(document['body'])
        document['id'] = _recompute_id(document)
        renamed.append(json.dumps(document, ensure_ascii=True, sort_keys=True,
                                  separators=(',', ':')))
    return tuple(renamed), mapping


def piece_ids_for(pieces, endpoint):
    for text in pieces:
        document = json.loads(text)
        names = {
            name
            for candidate in document['body']['candidates']
            for match in candidate['matches']
            for name in match
        }
        if endpoint in names:
            return document['id']
    raise KeyError(endpoint)


if __name__ == '__main__':
    unittest.main()
