"""Runtime demo: occlusion contrast, stop-station issuance and reclaim by id.

The script uses real SQLite databases in a temporary directory and walks
through the V2 partial handoff workflow end to end:

  * station-side opening of one handoff with frozen A/B/C revisions;
  * separate edge issuance where every edge only reads its own two sides;
  * the V1 occlusion contrast (same inputs give empty V1 edges);
  * center-side stop-station publication, including the sign-empty case,
    the half-turn double-pose case and its origin-probe collapse;
  * mixed-handoff rejection;
  * a station amendment followed by reopening the center and reclaiming the
    unchanged archived values by report number, with the stored receipt.
"""
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from database import open_database
from overlap.exchange import export_evidence
from overlap.issue import freeze, freeze_partial, open_partial, export_partial_links
from partial_cases import (
    CASE_MARKERS, EXPECTED, PROBES, ROLES, ZERO_PROBES, record_case,
)
from report.export import export_partial
from report.history import get_partial
from report.partial_store import PartialReportStore
from report.publication import publish_partial
from report.store import ReportStore
from survey.corrections import amend
from survey.store import ObservationStore


def emit(payload) -> None:
    print('PARTIAL_DEMO ' + json.dumps(payload, ensure_ascii=True, sort_keys=True))


def main() -> None:
    with TemporaryDirectory(prefix='contour-partial-') as directory:
        station_path = Path(directory) / 'station.sqlite'
        center_path = Path(directory) / 'center.sqlite'

        with open_database(station_path) as connection:
            observations = ObservationStore(connection)
            observations.initialize()
            revisions = {
                name: record_case(observations, name) for name in CASE_MARKERS
            }

            # Occlusion contrast: the same occluded inputs produce empty V1
            # edges, while the V2 edges each retain their identity candidate.
            for name in ('one_common', 'two_common'):
                v1_texts = tuple(
                    export_evidence(freeze(
                        observations, role,
                        revisions[name][source], revisions[name][target],
                    ))
                    for role, (source, target) in ROLES.items()
                )
                v1_counts = [
                    len(json.loads(text)['body']['transforms']) for text in v1_texts
                ]
                handoff = open_partial(observations, revisions[name])
                v2_texts = tuple(
                    freeze_partial(observations, handoff, role) for role in ROLES
                )
                v2_counts = [
                    len(json.loads(text)['body']['candidates']) for text in v2_texts
                ]
                links = export_partial_links(observations, handoff, v2_texts)
                emit({
                    'stage': 'occlusion_contrast',
                    'case': name,
                    'v1_edge_transform_counts': v1_counts,
                    'v2_edge_candidate_counts': v2_counts,
                    'v2_link_count': len(links),
                })

        archives = {}
        with open_database(center_path) as connection:
            reports = ReportStore(connection)
            PartialReportStore(connection).initialize()

            # Stop-station issuance for every reference case.
            with open_database(station_path) as station_connection:
                station = ObservationStore(station_connection)
                for name, expected in EXPECTED.items():
                    if name == 'half_turn_at_origin':
                        continue
                    handoff = open_partial(station, revisions[name])
                    pieces = tuple(
                        freeze_partial(station, handoff, role) for role in ROLES
                    )
                    links = export_partial_links(station, handoff, pieces)
                    archive = publish_partial(reports, pieces, links, PROBES)
                    emit({
                        'stage': 'stop_station_publication',
                        'case': name,
                        'report_id': archive['report_id'],
                        'handoff_id': archive['handoff_id'],
                        'status': archive['status'],
                        'pairs': archive['pairs'],
                        'expected_pairs': expected,
                        'receipt': archive['receipt'],
                    })
                    archives[name] = archive

                # Origin probes collapse the two opposite half-turn poses to
                # one pair of landing points.
                handoff = open_partial(station, revisions['half_turn'])
                pieces = tuple(
                    freeze_partial(station, handoff, role) for role in ROLES
                )
                origin_archive = publish_partial(
                    reports, pieces, export_partial_links(station, handoff, pieces),
                    ZERO_PROBES,
                )
                emit({
                    'stage': 'origin_probe_collapse',
                    'report_id': origin_archive['report_id'],
                    'pairs': origin_archive['pairs'],
                    'expected_pairs': EXPECTED['half_turn_at_origin'],
                })

                # Mixed handoff must be refused without producing a report.
                first = open_partial(station, revisions['two_common'])
                second = open_partial(station, revisions['two_common'])
                original = tuple(
                    freeze_partial(station, first, role) for role in ROLES
                )
                foreign = freeze_partial(station, second, 'AB')
                before = _report_count(connection)
                try:
                    publish_partial(
                        reports, (foreign, *original[1:]), (), PROBES,
                    )
                except ValueError as exc:
                    rejection = str(exc)
                else:
                    raise SystemExit('mixed handoff was accepted')
                after = _report_count(connection)
                emit({
                    'stage': 'mixed_handoff_rejected',
                    'reason': rejection,
                    'reports_before': before,
                    'reports_after': after,
                })

        # A late station amendment appends a revision; old archives survive.
        with open_database(station_path) as connection:
            amended = amend(ObservationStore(connection), revisions['two_common']['A'], [
                {'at': [2, 0], 'category': 'v', 'point': [3, 0]},
            ])
            emit({'stage': 'station_amendment', 'new_revision': amended})

        # Reopen the center and reclaim stored values by report number; no
        # pieces or links are needed at collection time.
        with open_database(center_path) as connection:
            reopened = ReportStore(connection)
            for name, archive in archives.items():
                report_id = archive['report_id']
                collected = get_partial(reopened, report_id)
                exported = json.loads(export_partial(reopened, report_id))
                assert collected == archive
                assert exported == archive
                emit({
                    'stage': 'reopen_reclaim',
                    'case': name,
                    'report_id': report_id,
                    'status': collected['status'],
                    'pairs': collected['pairs'],
                    'receipt': collected['receipt'],
                    'export_matches_archive': exported == collected,
                })


def _report_count(connection) -> int:
    return connection.execute('SELECT COUNT(*) FROM partial_reports').fetchone()[0]


if __name__ == '__main__':
    main()
