"""Synthetic, local-only S3 integration fixture. Never uses AWS endpoints."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

ROOT = Path('/smoke')
BUCKET = 'runix-synthetic-smoke'


def main(phase):
    client = boto3.client('s3', endpoint_url='http://objectstore:9000',
                          region_name='us-east-1',
                          config=Config(s3={'addressing_style': 'path'},
                                        connect_timeout=2, read_timeout=5,
                                        retries={'max_attempts': 1}))
    if phase == 'seed':
        for attempt in range(30):
            try:
                client.list_buckets()
                break
            except (BotoCoreError, ClientError):
                if attempt == 29:
                    raise RuntimeError('Local object store did not become ready') from None
                time.sleep(1)
        client.create_bucket(Bucket=BUCKET)
        payload = os.urandom(4 * 1024 * 1024)
        (ROOT / 'source.bin').write_bytes(payload)
        (ROOT / 'upload.bin').write_bytes(os.urandom(4 * 1024 * 1024))
        client.put_object(Bucket=BUCKET, Key='source.bin', Body=payload)
        print('PASS: independently seeded 4194304-byte S3-compatible object')
    elif phase == 'verify-upload':
        body = client.get_object(Bucket=BUCKET, Key='upload.bin')['Body'].read()
        if body != (ROOT / 'upload.bin').read_bytes():
            raise RuntimeError('Write-through object differs from source bytes')
        (ROOT / 's3-upload.bin').write_bytes(body)
        print('PASS: independent object-store read matches engine write-through')
    elif phase == 'evidence':
        evidence = {}
        for name in ('source.bin', 'read-before.bin', 'read-after.bin',
                     'upload.bin', 's3-upload.bin', 'upload-after.bin'):
            data = (ROOT / name).read_bytes()
            evidence[name] = {'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        (ROOT / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
        print(json.dumps(evidence, indent=2))
    else:
        raise ValueError('Unknown fixture phase')


if __name__ == '__main__':
    main(sys.argv[1])
