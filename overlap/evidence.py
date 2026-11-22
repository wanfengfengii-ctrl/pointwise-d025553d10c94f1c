from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, fields
from hashlib import sha256
import json
from types import MappingProxyType

from measure import entity_id, label
from overlap.transforms import RigidTransform

ROLES = MappingProxyType({'AB': ('B', 'A'), 'AC': ('C', 'A'), 'BC': ('C', 'B')})
EXCHANGE_VERSION = 1


def validate_direction(role: str, source: str, target: str) -> None:
    if not isinstance(role, str) or ROLES.get(role) != (source, target):
        raise ValueError('invalid overlap role or direction')


def _digest(value: dict) -> str:
    canonical = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    return sha256(canonical.encode('ascii')).hexdigest()


def _is_digest(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    id: str
    batch: str
    role: str
    source_station: str
    source_revision: int
    target_station: str
    target_revision: int
    body_sha256: str

    def __post_init__(self):
        label(self.batch, 'batch')
        validate_direction(self.role, self.source_station, self.target_station)
        entity_id(self.source_revision, 'source revision number')
        entity_id(self.target_revision, 'target revision number')
        if self.source_revision == self.target_revision:
            raise ValueError('source and target must reference different revisions')
        if not _is_digest(self.body_sha256):
            raise ValueError('invalid evidence body digest')
        if not isinstance(self.id, str) or not self.id.startswith('ov1-') or not _is_digest(self.id[4:]):
            raise ValueError('invalid evidence identity')
        source = self.to_dict()
        del source['id']
        if self.id != 'ov1-' + _digest({'version': EXCHANGE_VERSION, 'ref': source}):
            raise ValueError('evidence identity does not match source fields')

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Mapping):
        if not isinstance(value, Mapping) or set(value) != {field.name for field in fields(cls)}:
            raise ValueError('invalid evidence reference fields')
        return cls(**value)


@dataclass(frozen=True, slots=True)
class OverlapEvidence:
    ref: EvidenceRef
    transforms: tuple[RigidTransform, ...]


def body_data(transforms: tuple[RigidTransform, ...]) -> dict:
    return {
        'transforms': [[str(t.c), str(t.s), str(t.tx), str(t.ty)] for t in transforms],
    }


def make_evidence(
    batch: str, role: str, source_station: str, source_revision: int,
    target_station: str, target_revision: int, transforms: Iterable[RigidTransform],
) -> OverlapEvidence:
    supplied = tuple(transforms)
    if any(not isinstance(transform, RigidTransform) for transform in supplied):
        raise ValueError('expected rigid transforms in evidence body')
    canonical = tuple(sorted(set(supplied)))
    fields_by_name = {
        'batch': batch,
        'role': role,
        'source_station': source_station,
        'source_revision': source_revision,
        'target_station': target_station,
        'target_revision': target_revision,
        'body_sha256': _digest(body_data(canonical)),
    }
    identity = 'ov1-' + _digest({'version': EXCHANGE_VERSION, 'ref': fields_by_name})
    return OverlapEvidence(EvidenceRef(id=identity, **fields_by_name), canonical)
