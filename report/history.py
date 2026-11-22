from report.partial_store import PartialReportStore
from report.store import ReportSnapshot, ReportStore


def get(store: ReportStore, report_id: int) -> ReportSnapshot:
    return store.read_publication(report_id)


def get_partial(store: ReportStore, report_id: int) -> dict:
    if not isinstance(store, ReportStore):
        raise ValueError('get_partial requires a ReportStore')
    return PartialReportStore(store.connection).read_partial(report_id)
