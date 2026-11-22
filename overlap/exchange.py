import json

from overlap.evidence import EXCHANGE_VERSION, EvidenceRef, OverlapEvidence, body_data, make_evidence
from overlap.transforms import RigidTransform


def _unique_members(entries):
    document = {}
    for key, value in entries:
        if key in document:
            raise ValueError(f'duplicate evidence JSON member: {key}')
        document[key] = value
    return document


def export_evidence(piece: OverlapEvidence) -> str:
    document = {
        'version': EXCHANGE_VERSION,
        'ref': piece.ref.to_dict(),
        'body': body_data(piece.transforms),
    }
    return json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def verify_evidence(text: str) -> OverlapEvidence:
    if not isinstance(text, str):
        raise ValueError('expected evidence JSON text')
    document = json.loads(text, object_pairs_hook=_unique_members)
    if not isinstance(document, dict) or set(document) != {'version', 'ref', 'body'}:
        raise ValueError('invalid evidence envelope')
    version = document['version']
    if type(version) is not int or version != EXCHANGE_VERSION:
        raise ValueError('unsupported evidence version')
    ref = EvidenceRef.from_dict(document['ref'])
    body = document['body']
    if not isinstance(body, dict) or set(body) != {'transforms'} or not isinstance(body['transforms'], list):
        raise ValueError('invalid evidence transform body')
    candidates = []
    for row in body['transforms']:
        if not isinstance(row, list) or len(row) != 4 or any(not isinstance(value, str) for value in row):
            raise ValueError('each transform must contain four rational strings')
        candidates.append(RigidTransform(*row))
    restored = make_evidence(
        ref.batch, ref.role, ref.source_station, ref.source_revision,
        ref.target_station, ref.target_revision, candidates,
    )
    if body_data(restored.transforms) != body:
        raise ValueError('noncanonical evidence body')
    if restored.ref != ref:
        raise ValueError('evidence body or source checksum mismatch')
    return restored
