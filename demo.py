import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from analysis.execute import evaluate
from database import open_database
from measure import pairs_data
from overlap.evidence import ROLES
from overlap.exchange import export_evidence
from overlap.issue import freeze
from report.export import export_report
from report.publication import publish
from report.store import ReportStore
from review.intake import order
from review.store import OrderStore
from survey.corrections import amend
from survey.intake import record
from survey.store import ObservationStore

SAMPLE_FILES = {'rotated': 'rotated.json', 'symmetric': 'symmetric.json'}
EXPECTED = {
    'rotated': [[['1', '0'], ['1', '1']]],
    'symmetric': [[['-1', '0'], ['1', '0']], [['1', '0'], ['-1', '0']]],
}


def load_sample(case: str) -> dict:
    path = Path(__file__).with_name('samples') / SAMPLE_FILES[case]
    return json.loads(path.read_text(encoding='utf-8'))


def issue_selection(store: ObservationStore, edges: dict, revisions: dict) -> tuple[str, ...]:
    pieces = []
    for role in ROLES:
        source, target = edges[role]
        piece = freeze(store, role, revisions[source], revisions[target])
        pieces.append(export_evidence(piece))
    return tuple(pieces)


def issue_sample(store: ObservationStore, sample: dict) -> tuple[dict[str, int], tuple[str, ...]]:
    revisions = {
        name: record(store, sample['batch'], observation['station'], observation['markers'])
        for name, observation in sample['observations'].items()
    }
    return revisions, issue_selection(store, sample['edges'], revisions)


def _require_equal(expected, actual, marker: str) -> None:
    if actual != expected:
        raise SystemExit(f'{marker} expected={expected!r} actual={actual!r}')


def _run_case(case: str) -> None:
    sample = load_sample(case)
    with TemporaryDirectory(prefix='contour-review-') as directory:
        station_path = Path(directory) / 'station.sqlite'
        center_path = Path(directory) / 'center.sqlite'
        with open_database(station_path) as connection:
            observations = ObservationStore(connection)
            observations.initialize()
            revisions, pieces = issue_sample(observations, sample)

        expected = {'status': 'aligned', 'pairs': EXPECTED[case]}
        with open_database(center_path) as connection:
            orders = OrderStore(connection)
            reports = ReportStore(connection)
            orders.initialize()
            reports.initialize()
            fixed = order(orders, pieces, sample['probes'])
            outcome = evaluate(orders.read_order(fixed.id), pieces)
            actual = {'status': outcome.status, 'pairs': pairs_data(outcome.pairs)}
            _require_equal(expected, actual, 'JOINT_POSE_MISMATCH')
            original = publish(reports, outcome)

        corrected = None
        if 'correction' in sample:
            correction = sample['correction']
            key = correction['observation']
            with open_database(station_path) as connection:
                observations = ObservationStore(connection)
                revised = amend(observations, revisions[key], correction['replacements'])
                selected = {**revisions, key: revised}
                revised_pieces = issue_selection(observations, sample['edges'], selected)
            with open_database(center_path) as connection:
                orders = OrderStore(connection)
                reports = ReportStore(connection)
                fixed_new = order(orders, revised_pieces, sample['probes'])
                corrected = publish(reports, evaluate(fixed_new, revised_pieces))

        with open_database(center_path) as connection:
            reports = ReportStore(connection)
            collected = json.loads(export_report(reports, original.id))
            if corrected is not None:
                new_data = json.loads(export_report(reports, corrected.id))
                _require_equal([[['2', '0'], ['2', '1']]], new_data['pairs'], 'CORRECTION_MISMATCH')
                _require_equal(corrected.id, new_data['receipt']['report_id'], 'RECEIPT_MISMATCH')
                _require_equal(revised, new_data['references'][0]['target_revision'], 'SOURCE_MISMATCH')

        downstream_expected = {
            **expected,
            'references': [json.loads(text)['ref'] for text in pieces],
            'receipt': {'id': f'RCP-{original.id}', 'order_id': fixed.id, 'report_id': original.id},
        }
        downstream_actual = {key: collected[key] for key in downstream_expected}
        _require_equal(downstream_expected, downstream_actual, 'ARCHIVE_MISMATCH')
        scenario = {
            'case_id': 'V3' if case == 'rotated' else 'V6',
            'input': {
                'batch': sample['batch'], 'edges': sample['edges'],
                'observations': sample['observations'], 'probes': sample['probes'],
            },
            'expected': expected,
            'actual': actual,
            'downstream_expected': downstream_expected,
            'downstream_actual': downstream_actual,
            'code_paths': [
                'overlap/registration.py', 'overlap/issue.py', 'review/received.py',
                'analysis/alignment.py', 'analysis/projection.py', 'report/publication.py',
                'report/store.py', 'report/export.py',
            ],
            'oracle': (
                'Apply B to A after the local C to B translation by hand.' if case == 'rotated'
                else 'A unique half-turn on BC forces AB and AC to have opposite signs.'
            ),
        }
        print('POINTWISE_SCENARIO ' + json.dumps(scenario, sort_keys=True))
        if corrected is not None:
            print(json.dumps({'corrected_report': new_data, 'original_report_id': collected['report_id']}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(description='Run the contour review sample workflow.')
    parser.add_argument('--case', choices=('all', *SAMPLE_FILES), default='all')
    arguments = parser.parse_args()
    cases = SAMPLE_FILES if arguments.case == 'all' else (arguments.case,)
    for case in cases:
        _run_case(case)


if __name__ == '__main__':
    main()
