"""V2 partial edge pieces: canonical JSON, content identity and verification.

Endpoint identifiers reference station-local records through opaque,
handoff-scoped names.  The same station record uses the same endpoint
identifier in every candidate and every edge of a handoff, while a new
handoff mints an isolated namespace.  Raw coordinates, categories and
station-local marker keys never appear in the wire texts.
"""
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
import json

from measure import label
from overlap.evidence import ROLES, validate_direction
from overlap.handoff import (
    PartialHandoff, endpoint_identifier, shared_endpoint_index,
)
from overlap.partial_registration import PartialCandidate
from overlap.transforms import RigidTransform
from survey.revisions import ObservationRevision

PARTIAL_VERSION = 2
PARTIAL_PREFIX = 'ov2-'


def _digest(value: dict) -> str:
    canonical = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(',', ':'))
    return sha256(canonical.encode('ascii')).hexdigest()


def _is_digest(value) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in '0123456789abcdef' for character in value
    )


def _canonical_transform(transform: RigidTransform) -> list[str]:
    return [str(transform.c), str(transform.s), str(transform.tx), str(transform.ty)]


@dataclass(frozen=True, slots=True)
class PartialPiece:
    handoff_id: str
    id: str
    batch: str
    role: str
    source_revision: int
    target_revision: int
    body_sha256: str
    body: dict = field(compare=True)
    # Endpoint identifier -> (station, position) for resolving links at the
    # center; not part of the exported text.
    endpoints: Mapping[str, tuple[str, tuple]] = field(compare=False, default_factory=dict)

    @property
    def source_station(self) -> str:
        return ROLES[self.role][0]

    @property
    def target_station(self) -> str:
        return ROLES[self.role][1]


def build_partial_piece(
    handoff: PartialHandoff,
    role: str,
    source: ObservationRevision,
    target: ObservationRevision,
    candidates: tuple[PartialCandidate, ...],
) -> PartialPiece:
    if not isinstance(handoff, PartialHandoff):
        raise ValueError('a partial piece requires a partial handoff handle')
    validate_direction(role, source.station, target.station)
    if source.batch != target.batch or source.batch != handoff.batch:
        raise ValueError('partial edges must belong to the handoff batch')
    if (source.id, target.id) != (
        handoff.revision_for(source.station), handoff.revision_for(target.station),
    ):
        raise ValueError('edge revisions must be the frozen handoff revisions')
    if any(not isinstance(candidate, PartialCandidate) for candidate in candidates):
        raise ValueError('partial candidates must come from exact registration')

    ordinals = {
        source.station: shared_endpoint_index(source.markers),
        target.station: shared_endpoint_index(target.markers),
    }

    def endpoint(station: str, position: tuple) -> str:
        return endpoint_identifier(handoff.handoff_id, station, ordinals[station][position])

    body_candidates = []
    endpoint_records: dict[str, tuple[str, tuple]] = {}
    for candidate in candidates:
        matches = []
        for source_marker, target_marker in candidate.matches:
            source_endpoint = endpoint(source.station, source_marker.position)
            target_endpoint = endpoint(target.station, target_marker.position)
            endpoint_records[source_endpoint] = (source.station, source_marker.position)
            endpoint_records[target_endpoint] = (target.station, target_marker.position)
            matches.append([source_endpoint, target_endpoint])
        body_candidates.append({
            'transform': _canonical_transform(candidate.transform),
            'matches': sorted(matches),
        })
    body = {'candidates': body_candidates}
    body_sha256 = _digest(body)
    provenance = {
        'version': PARTIAL_VERSION,
        'handoff_id': handoff.handoff_id,
        'batch': label(source.batch, 'batch'),
        'role': role,
        'source_revision': source.id,
        'target_revision': target.id,
        'body_sha256': body_sha256,
    }
    piece_id = PARTIAL_PREFIX + _digest(provenance)
    return PartialPiece(
        handoff.handoff_id, piece_id, source.batch, role, source.id, target.id,
        body_sha256, body, dict(sorted(endpoint_records.items())),
    )


def export_partial_piece(piece: PartialPiece) -> str:
    document = {
        'version': PARTIAL_VERSION,
        'handoff_id': piece.handoff_id,
        'id': piece.id,
        'batch': piece.batch,
        'role': piece.role,
        'source_revision': piece.source_revision,
        'target_revision': piece.target_revision,
        'body_sha256': piece.body_sha256,
        'body': piece.body,
    }
    return json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def _unique_members(entries):
    document = {}
    for key, value in entries:
        if key in document:
            raise ValueError(f'duplicate partial JSON member: {key}')
        document[key] = value
    return document


def verify_partial_piece(text: str) -> PartialPiece:
    if not isinstance(text, str):
        raise ValueError('expected a partial piece JSON text')
    try:
        document = json.loads(text, object_pairs_hook=_unique_members)
    except json.JSONDecodeError as exc:
        raise ValueError('invalid partial piece JSON') from exc
    expected_fields = {
        'version', 'handoff_id', 'id', 'batch', 'role', 'source_revision',
        'target_revision', 'body_sha256', 'body',
    }
    if not isinstance(document, dict) or set(document) != expected_fields:
        raise ValueError('invalid partial piece envelope')
    if type(document['version']) is not int or document['version'] != PARTIAL_VERSION:
        raise ValueError('unsupported partial piece version')
    handoff_id = document['handoff_id']
    if not isinstance(handoff_id, str) or not handoff_id:
        raise ValueError('invalid handoff identifier')
    label(document['batch'], 'batch')
    role = document['role']
    if role not in ROLES:
        raise ValueError('invalid partial edge role')
    if type(document['source_revision']) is not int or type(document['target_revision']) is not int:
        raise ValueError('partial revisions must be integers')
    if document['source_revision'] == document['target_revision']:
        raise ValueError('source and target must reference different revisions')
    if not _is_digest(document['body_sha256']):
        raise ValueError('invalid partial body digest')
    body = document['body']
    if not isinstance(body, dict) or set(body) != {'candidates'} or not isinstance(body['candidates'], list):
        raise ValueError('invalid partial candidate body')
    seen_transforms = set()
    for candidate in body['candidates']:
        if not isinstance(candidate, dict) or set(candidate) != {'transform', 'matches'}:
            raise ValueError('each partial candidate needs transform and matches')
        transform_row = candidate['transform']
        if (
            not isinstance(transform_row, list) or len(transform_row) != 4
            or any(not isinstance(value, str) for value in transform_row)
        ):
            raise ValueError('each transform must contain four rational strings')
        transform = RigidTransform(*transform_row)
        if transform in seen_transforms:
            raise ValueError('duplicate partial candidate transform')
        seen_transforms.add(transform)
        matches = candidate['matches']
        if not isinstance(matches, list) or len(matches) < 2:
            raise ValueError('each partial candidate needs at least two matches')
        candidate_endpoints = set()
        for match in matches:
            if (
                not isinstance(match, list) or len(match) != 2
                or any(not isinstance(endpoint, str) or not endpoint for endpoint in match)
            ):
                raise ValueError('each match must contain two non-empty endpoint identifiers')
            if match[0] == match[1] or match[0] in candidate_endpoints or match[1] in candidate_endpoints:
                raise ValueError('a candidate cannot reference one endpoint record twice')
            candidate_endpoints.update(match)
        if matches != sorted(matches):
            raise ValueError('noncanonical partial match order')
    canonical_body = {'candidates': body['candidates']}
    if _digest(canonical_body) != document['body_sha256']:
        raise ValueError('partial body checksum mismatch')
    provenance = {
        'version': PARTIAL_VERSION,
        'handoff_id': handoff_id,
        'batch': document['batch'],
        'role': role,
        'source_revision': document['source_revision'],
        'target_revision': document['target_revision'],
        'body_sha256': document['body_sha256'],
    }
    expected_id = PARTIAL_PREFIX + _digest(provenance)
    if not isinstance(document['id'], str) or document['id'] != expected_id:
        raise ValueError('partial piece identity does not match its provenance')
    # Candidate transforms must be stored in canonical numeric order and
    # matches must be canonically ordered pairs.
    ordered_transforms = [
        RigidTransform(*candidate['transform']) for candidate in body['candidates']
    ]
    if ordered_transforms != sorted(ordered_transforms):
        raise ValueError('noncanonical partial candidate order')
    return PartialPiece(
        handoff_id, document['id'], document['batch'], role,
        document['source_revision'], document['target_revision'],
        document['body_sha256'], body, {},
    )
