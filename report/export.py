from dataclasses import asdict
import json

from measure import pairs_data
from report.history import get, get_partial
from report.partial_store import canonical_archive
from report.store import ReportStore


def export_report(store: ReportStore, report_id: int) -> str:
    snapshot = get(store, report_id)
    outcome = snapshot.outcome
    document = {
        'report_id': snapshot.id,
        'order_id': outcome.order_id,
        'batch': outcome.batch,
        'references': [ref.to_dict() for ref in outcome.references],
        'points': outcome.points.to_dict(),
        'status': outcome.status,
        'pairs': pairs_data(outcome.pairs),
        'receipt': asdict(snapshot.receipt),
    }
    return json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def export_partial(store: ReportStore, report_id: int) -> str:
    return canonical_archive(get_partial(store, report_id))
