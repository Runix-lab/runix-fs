"""Run only inside an isolated synthetic SDK container; never contacts AWS."""
import os
import socket

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError


def main():
    config = Config(signature_version='s3v4', s3={'addressing_style': 'path'},
                    connect_timeout=2, read_timeout=3,
                    retries={'total_max_attempts': 1}, ignore_configured_endpoint_urls=True)
    def client(access, secret):
        return boto3.client('s3', endpoint_url='http://objectstore:9000',
                            region_name='us-east-1', aws_access_key_id=access,
                            aws_secret_access_key=secret, config=config)
    local = client(os.environ['AWS_ACCESS_KEY_ID'], os.environ['AWS_SECRET_ACCESS_KEY'])
    body = local.get_object(Bucket='runix-synthetic-smoke', Key='source.bin')['Body']
    with body:
        if len(body.read()) != 4 * 1024 * 1024:
            raise RuntimeError('Own-store positive control failed')
    try:
        connection = socket.create_connection((os.environ['RUNIX_PEER_IP'], 9000), timeout=3)
    except (TimeoutError, OSError):
        pass
    else:
        connection.close()
        raise RuntimeError('Peer store unexpectedly reachable across private networks')
    foreign = client(os.environ['RUNIX_PEER_ACCESS'], os.environ['RUNIX_PEER_SECRET'])
    try:
        foreign.get_object(Bucket='runix-synthetic-smoke', Key='source.bin')
    except ClientError as error:
        if (error.response.get('ResponseMetadata', {}).get('HTTPStatusCode') != 403
                or error.response.get('Error', {}).get('Code') not in {
                    'AccessDenied', 'InvalidAccessKeyId', 'SignatureDoesNotMatch'}):
            raise RuntimeError('Unexpected foreign-credential response') from None
    else:
        raise RuntimeError('Peer credentials unexpectedly read local data')
    print('PASS: own-store read; peer network denied; foreign credentials denied')


if __name__ == '__main__':
    main()
