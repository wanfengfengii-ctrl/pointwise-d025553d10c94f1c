from report.store import ReportSnapshot, ReportStore


def get(store: ReportStore, report_id: int) -> ReportSnapshot:
    return store.read_publication(report_id)
