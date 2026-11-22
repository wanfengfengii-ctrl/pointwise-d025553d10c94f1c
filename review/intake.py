from collections.abc import Iterable, Mapping

from review.bindings import ReviewOrder, bind_order
from review.points import bind_points
from review.received import receive_pieces
from review.store import OrderStore


def order(store: OrderStore, pieces: Iterable[str], named_points: Mapping) -> ReviewOrder:
    received = receive_pieces(pieces)
    points = bind_points(named_points)
    return store.insert_order(bind_order(received, points))
