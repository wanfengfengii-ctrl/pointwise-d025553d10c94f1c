from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction

from measure import Point, point, rational


@dataclass(frozen=True, order=True, slots=True)
class RigidTransform:
    c: Fraction
    s: Fraction
    tx: Fraction
    ty: Fraction

    def __post_init__(self):
        for field in ('c', 's', 'tx', 'ty'):
            object.__setattr__(self, field, rational(getattr(self, field)))
        if self.c * self.c + self.s * self.s != 1:
            raise ValueError('rigid transform needs a unit rotation')

    def apply(self, position: Point) -> Point:
        x, y = point(position)
        return self.c * x - self.s * y + self.tx, self.s * x + self.c * y + self.ty

    def compose(self, inner: RigidTransform) -> RigidTransform:
        """Apply inner first and then this transform."""
        c = self.c * inner.c - self.s * inner.s
        s = self.s * inner.c + self.c * inner.s
        tx, ty = self.apply((inner.tx, inner.ty))
        return RigidTransform(c, s, tx, ty)


def transform_from_pairs(
    source_first: Point, source_second: Point,
    target_first: Point, target_second: Point,
) -> RigidTransform | None:
    sx, sy = point(source_first)
    sx2, sy2 = point(source_second)
    tx, ty = point(target_first)
    tx2, ty2 = point(target_second)
    dx, dy = sx2 - sx, sy2 - sy
    ex, ey = tx2 - tx, ty2 - ty
    length_squared = dx * dx + dy * dy
    if length_squared == 0 or length_squared != ex * ex + ey * ey:
        return None
    c = (dx * ex + dy * ey) / length_squared
    s = (dx * ey - dy * ex) / length_squared
    return RigidTransform(c, s, tx - c * sx + s * sy, ty - s * sx - c * sy)
