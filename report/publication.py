from analysis.outcome import ReviewOutcome
from report.partial_publication import publish_partial
from report.store import ReportSnapshot, ReportStore
from review.store import OrderStore

__all__ = ('publish', 'publish_partial')


def publish(store: ReportStore, outcome: ReviewOutcome) -> ReportSnapshot:
    if not isinstance(outcome, ReviewOutcome):
        raise ValueError('publish requires a review outcome')
    fixed = OrderStore(store.connection).read_order(outcome.order_id)
    if (outcome.batch, outcome.references, outcome.points) != (
        fixed.batch, fixed.references, fixed.points,
    ):
        raise ValueError('outcome does not match the persisted review order')
    return store.commit_publication(outcome)
