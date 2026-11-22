from dataclasses import asdict
import json

from measure import pairs_data
from report.history import get
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
