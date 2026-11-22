from dataclasses import dataclass

from measure import entity_id


@dataclass(frozen=True, slots=True)
class Receipt:
    id: str
    report_id: int
    order_id: int

    def __post_init__(self):
        entity_id(self.report_id, 'report number')
        entity_id(self.order_id, 'order number')
        if self.id != f'RCP-{self.report_id}':
            raise ValueError('receipt identity does not match report number')


def make_receipt(report_id: int, order_id: int) -> Receipt:
    return Receipt(f'RCP-{report_id}', report_id, order_id)
