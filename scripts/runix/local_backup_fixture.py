"""Bounded synthetic object backup/restore inside a private SDK container."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

BUCKET = 'runix-synthetic-smoke'
KEYS = ('source.bin', 'upload.bin')
SIZE = 4 * 1024 * 1024


def export_objects(client, root):
    listing = client.list_objects_v2(Bucket=BUCKET, MaxKeys=3)
    if (listing.get('IsTruncated') is not False
            or sorted(item.get('Key', '') for item in listing.get('Contents', [])) != list(KEYS)):
        raise ValueError('Unexpected or incomplete synthetic object inventory')
    backup = root / 'backup'
    backup.mkdir(mode=0o700)
    objects = {}
    for key in KEYS:
        body = client.get_object(Bucket=BUCKET, Key=key)['Body']
        with body:
            data = body.read(SIZE + 1)
        if len(data) != SIZE:
            raise ValueError('Unexpected synthetic object size')
        (backup / key).write_bytes(data)
        objects[key] = {'bytes': SIZE, 'sha256': hashlib.sha256(data).hexdigest()}
    manifest = {'version': 1, 'objects': objects}
    (backup / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def import_objects(client, root):
    backup = root / 'backup'
    manifest_path = backup / 'manifest.json'
    if manifest_path.stat().st_size > 4096:
        raise ValueError('Oversized backup manifest')
    manifest = json.loads(manifest_path.read_text())
    if (not isinstance(manifest, dict) or set(manifest) != {'version', 'objects'}
            or type(manifest['version']) is not int or manifest['version'] != 1
            or not isinstance(manifest['objects'], dict)
            or set(manifest['objects']) != set(KEYS)):
        raise ValueError('Unexpected backup manifest')
    payloads = {}
    for key in KEYS:
        item = manifest['objects'][key]
        if (not isinstance(item, dict) or set(item) != {'bytes', 'sha256'}
                or type(item['bytes']) is not int or item['bytes'] != SIZE
                or (backup / key).stat().st_size != SIZE):
            raise ValueError('Unexpected backup object metadata')
        data = (backup / key).read_bytes()
        if hashlib.sha256(data).hexdigest() != item['sha256']:
            raise ValueError('Backup object checksum mismatch')
        payloads[key] = data
    # Validate every byte before performing any destination mutation.
    client.create_bucket(Bucket=BUCKET)
    for key, data in payloads.items():
        client.put_object(Bucket=BUCKET, Key=key, Body=data)
    for key, expected in payloads.items():
        body = client.get_object(Bucket=BUCKET, Key=key)['Body']
        with body:
            actual = body.read(SIZE + 1)
        if actual != expected:
            raise ValueError('Imported object readback mismatch')
    return manifest


def main(phase):
    root = Path('/smoke')
    client = boto3.client('s3', endpoint_url='http://objectstore:9000',
                          region_name='us-east-1',
                          aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
                          aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'],
                          config=Config(signature_version='s3v4', s3={'addressing_style': 'path'},
                                        connect_timeout=2, read_timeout=3,
                                        retries={'total_max_attempts': 1},
                                        ignore_configured_endpoint_urls=True))
    for attempt in range(30):
        try:
            client.list_buckets()
            break
        except (BotoCoreError, ClientError):
            if attempt == 29:
                raise RuntimeError('Local fixture did not become ready') from None
            time.sleep(1)
    if phase == 'export':
        export_objects(client, root)
    elif phase == 'import':
        import_objects(client, root)
    elif phase == 'verify-new':
        body = client.get_object(Bucket=BUCKET, Key='restored-new.bin')['Body']
        with body:
            data = body.read(SIZE + 1)
        if data != (root / 'new.bin').read_bytes() or len(data) != SIZE:
            raise RuntimeError('Restored engine did not persist the new object correctly')
        (root / 'new-s3.bin').write_bytes(data)
    else:
        raise ValueError('Unknown backup fixture phase')
    print('PASS: local backup fixture ' + phase)


if __name__ == '__main__':
    main(sys.argv[1])
