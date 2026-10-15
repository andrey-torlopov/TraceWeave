#!/usr/bin/env python3
"""Validate E0 contracts, embedded examples and portable archive cross references.

No network fetches, plugin execution, database writes or automatic schema migration.
Dependencies are pinned in the workspace requirements; --self-test runs contract tests.
"""
from __future__ import annotations
import argparse
import calendar
import hashlib
import json
import math
import unicodedata
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
from typing import Any
from jsonschema import Draft202012Validator, FormatChecker, ValidationError, validators
from openapi_spec_validator import validate as validate_openapi

ROOT = Path(__file__).resolve().parents[1]
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


def strict_json(raw: str | bytes) -> Any:
    # json.loads(bytes) autodetects UTF-16/32; the wire/archive contract is UTF-8.
    if isinstance(raw, bytes):
        raw = raw.decode('utf-8', errors='strict')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'duplicate JSON key: {key}')
            result[key] = value
        return result
    def bad_constant(value):
        raise ValueError(f'non-finite JSON constant: {value}')
    def finite_float(value):
        parsed = float(value)
        if not math.isfinite(parsed):
            raise ValueError('non-finite JSON number')
        return parsed
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant, parse_float=finite_float)
    def unicode_scalars(node):
        if isinstance(node, str):
            # Unpaired escaped surrogates are accepted by Python JSON but are not
            # Unicode scalar values and cannot be represented as strict UTF-8.
            node.encode('utf-8', errors='strict')
        elif isinstance(node, dict):
            for key, child in node.items():
                unicode_scalars(key)
                unicode_scalars(child)
        elif isinstance(node, list):
            for child in node:
                unicode_scalars(child)
    unicode_scalars(value)
    return value


def _utf8_bytes(validator, limit, instance, schema):
    if isinstance(instance, str) and len(instance.encode('utf-8')) > limit:
        yield ValidationError('UTF-8 byte limit exceeded')


def _json_bytes(validator, limit, instance, schema):
    size = len(json.dumps(instance, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    if size > limit:
        yield ValidationError('JSON UTF-8 byte limit exceeded')


def _calendar_date(validator, enabled, instance, schema):
    if enabled and isinstance(instance, dict) and isinstance(instance.get('value'), str):
        try:
            parts = [int(value) for value in instance['value'].split('-')]
            year = parts[0]
            if not 1 <= year <= 9999:
                raise ValueError('invalid year')
            if len(parts) >= 2 and not 1 <= parts[1] <= 12:
                raise ValueError('invalid month')
            if len(parts) == 3 and not 1 <= parts[2] <= calendar.monthrange(year, parts[1])[1]:
                raise ValueError('invalid day')
        except (ValueError, IndexError):
            yield ValidationError('invalid real calendar date')


def _normalized(validator, rule, instance, schema):
    if isinstance(instance, str) and rule == 'NFC+trim':
        normalized = unicodedata.normalize('NFC', instance).strip()
        if not schema.get('minLength', 0) <= len(normalized) <= schema.get('maxLength', sys.maxsize):
            yield ValidationError('normalized text length outside bounds')


def _normalized_length_instance(instance, schema):
    # Wire input is normalized before standard scalar-length validation. The schemas
    # retain canonical limits for DTO consumers; this does not rewrite Markdown.
    if isinstance(instance, str) and schema.get('x-normalize') == 'NFC+trim':
        return unicodedata.normalize('NFC', instance).strip()
    return instance


def _min_length(validator, limit, instance, schema):
    yield from Draft202012Validator.VALIDATORS['minLength'](
        validator, limit, _normalized_length_instance(instance, schema), schema)


def _max_length(validator, limit, instance, schema):
    yield from Draft202012Validator.VALIDATORS['maxLength'](
        validator, limit, _normalized_length_instance(instance, schema), schema)


def _unique_normalized(validator, enabled, instance, schema):
    if enabled and isinstance(instance, list) and all(isinstance(x, str) for x in instance):
        normalized = [unicodedata.normalize('NFC', item).strip() for item in instance]
        if len(normalized) != len(set(normalized)):
            yield ValidationError('duplicate normalized value')


_EMOJI17 = frozenset(json.loads((ROOT / 'contracts/emoji/17.0.json').read_text())['sequences'])
def _emoji(validator, version, instance, schema):
    if isinstance(instance, str) and (version != '17.0' or instance not in _EMOJI17 or len(instance.encode('utf-8')) > 128):
        yield ValidationError('expected one qualified Emoji 17.0 sequence')


ContractValidator = validators.extend(Draft202012Validator, {
    'minLength': _min_length,
    'maxLength': _max_length,
    'x-maxUtf8Bytes': _utf8_bytes,
    'x-maxJsonUtf8Bytes': _json_bytes,
    'x-realCalendarDate': _calendar_date,
    'x-normalize': _normalized,
    'x-uniqueNormalized': _unique_normalized,
    'x-emojiVersion': _emoji,
})


def load_contracts():
    return (strict_json((ROOT / 'contracts/openapi.yaml').read_text()),
            strict_json((ROOT / 'contracts/archive-v1.schema.json').read_text()))


def schema_validator(name: str, api=None):
    if api is None:
        api, _ = load_contracts()
    return ContractValidator({'$ref': '#/components/schemas/' + name,
                              'components': api['components']}, format_checker=FormatChecker())


def archive_validator(name: str, archive=None):
    if archive is None:
        _, archive = load_contracts()
    return ContractValidator({'$ref': '#/$defs/' + name, '$defs': archive['$defs']},
                             format_checker=FormatChecker())


def walk(value, path=''):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, path + '/' + key.replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, path + '/' + str(index))


def resolve_ref(root, reference):
    if not reference.startswith('#/'):
        raise ValueError('external contract reference prohibited: ' + reference)
    value = root
    for segment in reference[2:].split('/'):
        value = value[segment.replace('~1', '/').replace('~0', '~')]
    return value


def validate_contracts():
    api, archive = load_contracts()
    validate_openapi(api)
    Draft202012Validator.check_schema(archive)
    for root in (api, archive):
        for path, value in walk(root):
            if isinstance(value, dict) and '$ref' in value:
                resolve_ref(root, value['$ref'])
            if isinstance(value, dict) and value.get('type') == 'object' and '/examples/' not in path:
                if value.get('additionalProperties') is True:
                    raise ValueError('unbounded object: ' + path)
                if 'properties' in value and 'additionalProperties' not in value:
                    # Partial conditional schemas refine a previously closed object.
                    if not any(part in path for part in ('/if/', '/then/', '/contains/')):
                        raise ValueError('object must explicitly close properties: ' + path)
    example_count = 0
    for name, schema in api['components']['schemas'].items():
        Draft202012Validator.check_schema(schema)
        for example in schema.get('examples', []):
            try:
                schema_validator(name, api).validate(example)
            except ValidationError as error:
                raise ValueError(f'invalid {name} example: {error.message}') from error
            example_count += 1
    for path, item in api['paths'].items():
        for method, operation in item.items():
            if method in ('get', 'head', 'post', 'put', 'delete', 'patch'):
                for pointer, value in walk(operation):
                    if isinstance(value, dict) and 'schema' in value and 'example' in value:
                        ContractValidator({**value['schema'], 'components': api['components']}, format_checker=FormatChecker()).validate(value['example'])
    return {'schemas': len(api['components']['schemas']), 'commandKinds': len(api['components']['schemas']['Command']['oneOf']),
            'operations': sum(len(value) for value in api['paths'].values()), 'examples': example_count,
            'archiveDefinitions': len(archive['$defs'])}


def validate_project(project: dict):
    """Archive domain cross-reference checks; never mutates or imports data."""
    archive_validator('Project').validate(project)
    inv = project['investigation']['id']
    collections = ('nodeTypes', 'relationTypes', 'nodes', 'attributes', 'relations', 'assets',
                   'attachments', 'evidence', 'reports', 'snapshots', 'deletionBatches', 'blobs')
    seen = set()
    indexes = {}
    for name in collections:
        indexes[name] = {}
        for row in project[name]:
            identifier = row['id']
            if identifier in seen:
                raise ValueError('duplicate object UUID')
            seen.add(identifier)
            indexes[name][identifier] = row
            if 'investigationId' in row and row['investigationId'] != inv:
                raise ValueError('cross-investigation object')
    for name in ('layouts', 'memberships', 'snapshotAssets'):
        if any(row['investigationId'] != inv for row in project[name]):
            raise ValueError('cross-investigation reference')
    def lookup(collection, identifier):
        if identifier not in indexes[collection]:
            raise ValueError(f'missing {collection} reference')
        return indexes[collection][identifier]
    def unique(values, message):
        if len(values) != len(set(values)):
            raise ValueError(message)
    unique([r['code'] for r in project['nodeTypes']], 'duplicate node type code')
    unique([r['code'] for r in project['relationTypes']], 'duplicate relation type code')
    for node in project['nodes']:
        lookup('nodeTypes', node['typeId'])
        if (node['deletedAt'] is None) != (node['deletionBatchId'] is None):
            raise ValueError('invalid deletion metadata')
        if node['deletionBatchId'] is not None:
            lookup('deletionBatches', node['deletionBatchId'])
    unique([r['nodeId'] for r in project['layouts']], 'duplicate layout')
    if set(r['nodeId'] for r in project['layouts']) != set(indexes['nodes']):
        raise ValueError('each node requires exactly one layout')
    unique([r['memberNodeId'] for r in project['memberships']], 'multiple group membership')
    for row in project['memberships']:
        group = lookup('nodes', row['groupNodeId']); member = lookup('nodes', row['memberNodeId'])
        gt = lookup('nodeTypes', group['typeId']); mt = lookup('nodeTypes', member['typeId'])
        if gt['code'] != 'group' or not gt['isSystem'] or mt['code'] == 'group' or group['deletedAt'] or member['deletedAt']:
            raise ValueError('invalid group membership')
    codes = {r['code'] for r in project['relationTypes']}
    for relation in project['relations']:
        source = lookup('nodes', relation['sourceNodeId']); target = lookup('nodes', relation['targetNodeId'])
        if source['id'] == target['id'] or relation['relationType'] not in codes:
            raise ValueError('invalid relation endpoints/type')
        if relation.get('bidirectional', False) and not relation['directed']:
            raise ValueError('bidirectional relation must be directed')
        if not relation['directed'] and source['id'] >= target['id']:
            raise ValueError('uncanonical undirected relation')
        if (relation['deletedAt'] is None) != (relation['deletionBatchId'] is None):
            raise ValueError('invalid relation deletion metadata')
        if relation['deletedAt'] is None:
            if source['deletedAt'] or target['deletedAt']:
                raise ValueError('active relation with deleted endpoint')
        else:
            lookup('deletionBatches', relation['deletionBatchId'])
    attr_keys = []
    for attribute in project['attributes']:
        lookup('nodes', attribute['nodeId'])
        import unicodedata
        normalized = unicodedata.normalize('NFC', attribute['key']).strip().casefold()
        if attribute['normalizedKey'] != normalized:
            raise ValueError('attribute key normalization mismatch')
        attr_keys.append((attribute['nodeId'], normalized))
    unique(attr_keys, 'duplicate attribute key')
    for blob in project['blobs']:
        if blob['path'] != 'blobs/' + blob['sha256']:
            raise ValueError('blob path/hash mismatch')
    for asset in project['assets']:
        blob = lookup('blobs', asset['blobId'])
        if asset['sha256'] != blob['sha256'] or asset['byteSize'] != blob['byteSize']:
            raise ValueError('asset/blob metadata mismatch')
        if (asset['deletedAt'] is None) != (asset['deletionBatchId'] is None):
            raise ValueError('invalid asset deletion metadata')
        if asset['deletionBatchId']:
            lookup('deletionBatches', asset['deletionBatchId'])
        if asset['mediaKind'] == 'text' and asset['byteSize'] > 5242880:
            raise ValueError('text asset exceeds limit')
    pairs = []; primary = []
    for attachment in project['attachments']:
        node = lookup('nodes', attachment['nodeId']); asset = lookup('assets', attachment['assetId'])
        if not node['deletedAt'] and asset['deletedAt']:
            raise ValueError('active attachment to trashed asset')
        pairs.append((node['id'], asset['id']))
        if attachment['role'] == 'primary':
            primary.append(node['id'])
    unique(pairs, 'duplicate attachment'); unique(primary, 'multiple primary attachments')
    for evidence in project['evidence']:
        lookup('nodes' if evidence['subjectKind'] == 'node' else 'relations', evidence['subjectId'])
        if evidence['sourceKind'] == 'node': lookup('nodes', evidence['sourceNodeId'])
        if evidence['sourceKind'] == 'asset': lookup('assets', evidence['assetId'])
    for report in project['reports']:
        for identifier in report['selectedNodeIds'] + report['orderedConclusionIds']:
            lookup('nodes', identifier)
    for snapshot in project['snapshots']:
        lookup('reports', snapshot['reportDefinitionId'])
        content = snapshot['content']
        if content['definition']['id'] != snapshot['reportDefinitionId'] or content['definition']['investigationId'] != inv:
            raise ValueError('snapshot definition identity mismatch')
        historical_types = {r['id']: r for r in content['nodeTypes']}
        historical_relation_types = {r['code']: r for r in content['relationTypes']}
        for node in content['nodes']:
            if node['typeId'] not in historical_types:
                raise ValueError('snapshot node missing historical type')
        for relation in content['relations']:
            if relation['relationType'] not in historical_relation_types:
                raise ValueError('snapshot relation missing historical type')
        # Frozen identities need not resolve to current live objects; validate inside the snapshot.
        historical_nodes = {r['id']: r for r in content['nodes']}
        historical_assets = {r['id']: r for r in content['assets']}
        historical_relations = {r['id']: r for r in content['relations']}
        for rows in (content['nodes'], content['assets'], content['relations']):
            unique([r['id'] for r in rows], 'duplicate snapshot object')
            if any(r['investigationId'] != inv for r in rows):
                raise ValueError('cross-investigation historical object')
        for relation in content['relations']:
            if relation['sourceNodeId'] not in historical_nodes or relation['targetNodeId'] not in historical_nodes:
                raise ValueError('snapshot relation missing historical endpoint')
        for attribute in content['attributes']:
            if attribute['nodeId'] not in historical_nodes:
                raise ValueError('snapshot attribute missing historical node')
        for attachment in content['attachments']:
            if attachment['nodeId'] not in historical_nodes or attachment['assetId'] not in historical_assets:
                raise ValueError('snapshot attachment missing historical object')
        for source in content['evidence']:
            evidence = source['evidence']
            subjects = historical_nodes if evidence['subjectKind'] == 'node' else historical_relations
            if evidence['subjectId'] not in subjects:
                raise ValueError('snapshot evidence subject missing')
            if source['sourceStatus'] == 'outside_scope' and source['sourceTitle'] is not None:
                raise ValueError('excluded source discloses historical metadata')
            if source['sourceStatus'] == 'included':
                if evidence['sourceKind'] == 'node' and evidence['sourceNodeId'] not in historical_nodes:
                    raise ValueError('snapshot included source missing')
                if evidence['sourceKind'] == 'asset' and evidence['assetId'] not in historical_assets:
                    raise ValueError('snapshot included asset missing')
    pins = []
    for pin in project['snapshotAssets']:
        snapshot = lookup('snapshots', pin['snapshotId']); lookup('assets', pin['assetId']); lookup('blobs', pin['blobId'])
        if not any(a['id'] == pin['assetId'] and a['blobId'] == pin['blobId'] for a in snapshot['content']['assets']):
            raise ValueError('snapshot pin mismatches historical asset')
        pins.append((pin['snapshotId'], pin['assetId']))
    unique(pins, 'duplicate snapshot pin')
    for snapshot in project['snapshots']:
        for asset in snapshot['content']['assets']:
            if (snapshot['id'], asset['id']) not in pins:
                raise ValueError('snapshot asset lacks immutable blob pin')
    for batch in project['deletionBatches']:
        for collection, key in [('nodes','nodeIds'),('relations','relationIds'),('assets','assetIds')]:
            for identifier in batch[key]: lookup(collection, identifier)
        for membership in batch['previousMemberships']:
            if membership['investigationId'] != inv:
                raise ValueError('cross-investigation prior membership')
            lookup('nodes', membership['groupNodeId']); lookup('nodes', membership['memberNodeId'])
    return project


def validate_archive_directory(directory: Path):
    """Validate an already isolated directory; ZIP extraction and streaming limits belong to E7."""
    directory = directory.resolve(strict=True)
    manifest_path = directory / 'manifest.json'
    if manifest_path.is_symlink(): raise ValueError('symlink manifest')
    manifest = strict_json(manifest_path.read_bytes())
    archive_validator('Manifest').validate(manifest)
    files = manifest['files']; paths = [item['path'] for item in files]
    if len(set(paths)) != len(paths): raise ValueError('duplicate manifest entry')
    if paths.count('project.json') != 1: raise ValueError('missing project.json')
    for entry in files:
        path = directory / PurePosixPath(entry['path'])
        if any(part.is_symlink() for part in (path, *path.parents) if part != directory.parent):
            raise ValueError('symlink archive entry')
        if not path.is_file() or not path.resolve().is_relative_to(directory):
            raise ValueError('missing or escaped archive entry')
        digest = hashlib.sha256(); count = 0
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024*1024), b''):
                count += len(chunk); digest.update(chunk)
                if count > entry['byteSize']: raise ValueError('archive size mismatch')
        if count != entry['byteSize'] or digest.hexdigest() != entry['sha256']:
            raise ValueError('archive hash/size mismatch')
    project = validate_project(strict_json((directory / 'project.json').read_bytes()))
    if project['investigation']['id'] != manifest['sourceInvestigationId'] or project['investigation']['revision'] != manifest['sourceRevision']:
        raise ValueError('manifest/project identity mismatch')
    entries_by_path = {entry['path']: entry for entry in files}
    for blob in project['blobs']:
        entry = entries_by_path.get(blob['path'])
        if entry is None or entry['sha256'] != blob['sha256'] or entry['byteSize'] != blob['byteSize']:
            raise ValueError('manifest/blob metadata mismatch')
    if set(paths) != {'project.json'} | {blob['path'] for blob in project['blobs']}:
        raise ValueError('manifest does not exactly enumerate originals')
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    if actual != set(paths) | {'manifest.json'}: raise ValueError('unlisted archive entry')
    return project


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--archive-directory', type=Path)
    args = parser.parse_args()
    try:
        result = validate_contracts()
        if args.archive_directory:
            validate_archive_directory(args.archive_directory)
        print(json.dumps(result, sort_keys=True))
        if args.self_test:
            return subprocess.call([sys.executable, '-m', 'unittest', 'discover', '-s', str(ROOT/'tests/contracts'), '-v'], cwd=ROOT)
        return 0
    except (ValueError, ValidationError, OSError) as error:
        print(f'Contract validation failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
