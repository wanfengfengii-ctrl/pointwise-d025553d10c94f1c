from fractions import Fraction

Point = tuple[Fraction, Fraction]
PointPair = tuple[Point, Point]
STATIONS = ('A', 'B', 'C')
MAX_SQLITE_ID = (1 << 63) - 1


def rational(value) -> Fraction:
    if type(value) is int or isinstance(value, (str, Fraction)):
        try:
            return Fraction(value)
        except (ValueError, ZeroDivisionError) as exc:
            raise ValueError('invalid rational coordinate') from exc
    raise ValueError('coordinate must be an exact rational')


def point(value) -> Point:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise ValueError('point must contain two coordinates')
    x, y = value
    return rational(x), rational(y)


def point_data(value: Point) -> list[str]:
    return [str(axis) for axis in value]


def pairs_data(pairs: tuple[PointPair, ...]) -> list[list[list[str]]]:
    return [[point_data(b), point_data(c)] for b, c in pairs]


def label(value, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip() or not value.isprintable():
        raise ValueError(f'invalid {field}')
    return value


def station_name(value) -> str:
    if not isinstance(value, str) or value not in STATIONS:
        raise ValueError('station must be A, B or C')
    return value


def entity_id(value, field: str) -> int:
    if type(value) is not int or not 1 <= value <= MAX_SQLITE_ID:
        raise ValueError(f'invalid {field}')
    return value
