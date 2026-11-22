"""Optional link materials binding endpoint identities across partial edges.

When the three edge pieces already use the same endpoint identifier for the
same station-local record, no link material is required and
:func:`build_partial_links` returns an empty tuple.  When identifiers are
edge-local, one link document per equivalence group records every piece
reference that denotes the same record.  Link bodies contain only opaque
endpoint identifiers and piece ids: raw marker data stays at the stations.
"""
from collections.abc import Iterable, Sequence
import json

from overlap.partial_piece import PARTIAL_VERSION, _digest, _is_digest, _unique_members

LINK_PREFIX = 'lnk2-'


def build_partial_links(piece_texts: Iterable[str]) -> tuple[str, ...]:
    documents = []
    handoff_id = None
    for text in piece_texts:
        document = json.loads(text)
        if document.get('version') != PARTIAL_VERSION:
            raise ValueError('links can only bind partial version 2 pieces')
        if handoff_id is None:
            handoff_id = document['handoff_id']
        elif document['handoff_id'] != handoff_id:
            raise ValueError('pieces belong to different handoffs')
        documents.append(document)

def build_partial_links(piece_texts: Iterable[str]) -> tuple[str, ...]:
    documents = []
    handoff_id = None
    for text in piece_texts:
        document = json.loads(text)
        if document.get('version') != PARTIAL_VERSION:
            raise ValueError('links can only bind partial version 2 pieces')
        if handoff_id is None:
            handoff_id = document['handoff_id']
        elif document['handoff_id'] != handoff_id:
            raise ValueError('pieces belong to different handoffs')
        documents.append(document)

    # Endpoint name -> pieces containing that exact name.
    owners_by_endpoint: dict[str, set[str]] = {}
    # Station -> endpoint names used on the two edges touching it.
    names_by_station: dict[str, set[str]] = {}
    for document in documents:
        source_station, target_station = _edge_stations(document['role'])
        names = {
            endpoint
            for candidate in document['body']['candidates']
            for match in candidate['matches']
            for endpoint in match
        }
        for endpoint in names:
            owners_by_endpoint.setdefault(endpoint, set()).add(document['id'])
            for station, token in (
                (source_station, f'-{source_station}'),
                (target_station, f'-{target_station}'),
            ):
                if token in endpoint:
                    names_by_station.setdefault(station, set()).add(endpoint)

    links = []
    for station in sorted(names_by_station):
        station_names = names_by_station[station]
        shared = {name for name in station_names if len(owners_by_endpoint[name]) >= 2}
        if not shared:
            # No self-proving names: every cross-edge identity on this
            # station must be supplied by explicit link material.
            for endpoint in sorted(station_names):
                owners = owners_by_endpoint[endpoint]
                body = {
                    'groups': [[
                        [piece_id, endpoint] for piece_id in sorted(owners)
                    ]]
                }
                links.append(_encode_link(handoff_id, body))
        # When the minted shared names exist they already carry the proof;
        # a station either self-proves consistently or links every record.
    return tuple(links)


def _edge_stations(role: str) -> tuple[str, str]:
    return {'AB': ('B', 'A'), 'AC': ('C', 'A'), 'BC': ('C', 'B')}[role]


def _encode_link(handoff_id: str, body: dict) -> str:
    body_sha256 = _digest(body)
    provenance = {
        'version': PARTIAL_VERSION,
        'handoff_id': handoff_id,
        'body_sha256': body_sha256,
    }
    link_id = LINK_PREFIX + _digest(provenance)
    document = {
        'version': PARTIAL_VERSION,
        'handoff_id': handoff_id,
        'id': link_id,
        'body_sha256': body_sha256,
        'body': body,
    }
    return json.dumps(document, ensure_ascii=True, sort_keys=True, separators=(',', ':'))


def verify_partial_links(
    texts: Sequence[str], handoff_id: str, piece_ids: set[str],
) -> tuple[frozenset[str], ...]:
    """Validate link texts and return equivalence groups of endpoint names."""
    if not isinstance(texts, Sequence):
        raise ValueError('links must be a sequence of JSON texts')
    groups: list[frozenset[str]] = []
    seen_ids: set[str] = set()
    for text in texts:
        if not isinstance(text, str):
            raise ValueError('expected a link JSON text')
        try:
            document = json.loads(text, object_pairs_hook=_unique_members)
        except json.JSONDecodeError as exc:
            raise ValueError('invalid link JSON') from exc
        if not isinstance(document, dict) or set(document) != {
            'version', 'handoff_id', 'id', 'body_sha256', 'body',
        }:
            raise ValueError('invalid link envelope')
        if type(document['version']) is not int or document['version'] != PARTIAL_VERSION:
            raise ValueError('unsupported link version')
        if document['handoff_id'] != handoff_id:
            raise ValueError('link belongs to a different handoff')
        if not isinstance(document['id'], str) or not document['id'].startswith(LINK_PREFIX):
            raise ValueError('invalid link identity')
        body = document['body']
        if not isinstance(body, dict) or set(body) != {'groups'} or not isinstance(body['groups'], list):
            raise ValueError('invalid link body')
        if not _is_digest(document['body_sha256']) or _digest(body) != document['body_sha256']:
            raise ValueError('link body checksum mismatch')
        expected_id = LINK_PREFIX + _digest({
            'version': PARTIAL_VERSION,
            'handoff_id': handoff_id,
            'body_sha256': document['body_sha256'],
        })
        if document['id'] != expected_id:
            raise ValueError('link identity does not match its provenance')
        if document['id'] in seen_ids:
            raise ValueError('duplicate link identity')
        seen_ids.add(document['id'])
        members: set[str] = set()
        for group in body['groups']:
            if not isinstance(group, list) or not group:
                raise ValueError('each link group must be a non-empty reference list')
            group_endpoints = set()
            for reference in group:
                if (
                    not isinstance(reference, list) or len(reference) != 2
                    or any(not isinstance(value, str) or not value for value in reference)
                ):
                    raise ValueError('each link reference needs a piece id and endpoint id')
                piece_id, endpoint = reference
                if piece_id not in piece_ids:
                    raise ValueError('link references a piece that was not delivered')
                group_endpoints.add(endpoint)
            members.update(group_endpoints)
        if not members:
            raise ValueError('link without endpoint references')
        groups.append(frozenset(members))
    return tuple(groups)
