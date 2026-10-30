"""Run a synthetic, private Docker-only S3 smoke, never AWS or production.

Requires cached images and the local SDK. Legacy mode uses the build volume;
--engine-artifact runs the pinned non-root image. No pulls or published ports.
"""
import argparse
import os
import secrets
import subprocess
import tempfile
import uuid
from pathlib import Path

TOOL_IMAGE = 'ghcr.io/curvineio/curvine-tests@sha256:841254160ea7b619964c5be225e1c5bb5891c1ec91f0d641c2a210db2701cb9d'
OBJECT_IMAGE = 'minio/minio@sha256:14cea493d9a34af32f524e538b8346cf79f3321eff8e708c1e2960462bd8936e'
SDK_IMAGE = 'python@sha256:5b8b1421ccb6a525860a77863c049eab5847076cda34e030c75a80c58faf3f3c'


def main(sdk_dir, engine_artifact=None):
    sdk = Path(sdk_dir).resolve(strict=True)
    if not (sdk / 'boto3').is_dir():
        raise ValueError('SDK directory must contain the existing boto3 package')
    image_fixture = None
    if engine_artifact is not None:
        from image_engine_fixture import ImageEngineFixture
        image_fixture = ImageEngineFixture(engine_artifact)
    fixture = Path(__file__).resolve().parent
    for image in ((OBJECT_IMAGE, SDK_IMAGE) if image_fixture else (TOOL_IMAGE, OBJECT_IMAGE, SDK_IMAGE)):
        subprocess.run(['docker', 'image', 'inspect', image], stdout=subprocess.DEVNULL, check=True)
    runtime = Path(tempfile.mkdtemp(prefix='runix-s3-smoke-'))
    runtime.chmod(0o700)
    print('Local synthetic evidence directory:', runtime, flush=True)
    account, secret = 'runixfixture', secrets.token_hex(24)
    envfile = runtime / 'fixture.env'
    descriptor = os.open(envfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        output.write(f'MINIO_ROOT_USER={account}\nMINIO_ROOT_PASSWORD={secret}\nAWS_ACCESS_KEY_ID={account}\nAWS_SECRET_ACCESS_KEY={secret}\nAWS_EC2_METADATA_DISABLED=true\n')
    suffix = uuid.uuid4().hex[:12]
    network = 'runix-s3-smoke-' + suffix
    store, engine, client = network + '-store', network + '-engine', network + '-client'
    created_network = False
    try:
        subprocess.run(['docker', 'network', 'create', '--internal', network], check=True, stdout=subprocess.DEVNULL)
        created_network = True
        subprocess.run(['docker', 'run', '-d', '--name', store, '--network', network,
                        '--network-alias', 'objectstore', '--env-file', str(envfile),
                        '--cpus', '1', '--memory', '1g', OBJECT_IMAGE,
                        'server', '/data', '--console-address', ':9001'],
                       check=True, stdout=subprocess.DEVNULL)
        def sdk_phase(phase):
            subprocess.run([
                'docker', 'run', '--rm', '--name', client, '--network', network,
                '--env-file', str(envfile), '--env', 'PYTHONPATH=/sdk',
                '--mount', f'type=bind,source={runtime},target=/smoke',
                '--mount', f'type=bind,source={fixture},target=/fixture,readonly',
                '--mount', f'type=bind,source={sdk},target=/sdk,readonly',
                SDK_IMAGE, 'python', '/fixture/local_s3_fixture.py', phase,
            ], check=True, timeout=90)
        sdk_phase('seed')
        if image_fixture:
            image_fixture.run(runtime, network, engine, envfile, fixture / 'local_s3_engine_smoke.sh')
        else:
            with (runtime / 'console.out').open('w') as log:
                completed = subprocess.run([
                    'docker', 'run', '--rm', '--name', engine, '--platform', 'linux/amd64',
                    '--network', network, '--env-file', str(envfile), '--cpus', '2', '--memory', '6g',
                    '--mount', 'type=volume,source=runix-fs-marketplace-target,target=/build,readonly',
                    '--mount', f'type=bind,source={runtime},target=/smoke',
                    '--mount', f'type=bind,source={fixture},target=/fixture,readonly',
                    TOOL_IMAGE, 'timeout', '420', 'bash', '/fixture/local_s3_engine_smoke.sh',
                ], stdout=log, stderr=subprocess.STDOUT, timeout=480)
            # The console contains only fixture phase results, not CLI mount output.
            print((runtime / 'console.out').read_text(), end='', flush=True)
            if completed.returncode:
                raise RuntimeError(f'Local S3 smoke failed: exit {completed.returncode}; private logs retained in {runtime}')
        sdk_phase('verify-upload')
        sdk_phase('evidence')
    finally:
        # A failed docker run may still leave a created container. All three
        # names are unique to this invocation, including failure cleanup.
        subprocess.run(['docker', 'rm', '-fv', engine, client, store], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if created_network:
            subprocess.run(['docker', 'network', 'rm', network], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Inert fixture-only credentials need not persist after the temporary server.
        envfile.unlink(missing_ok=True)
        if image_fixture:
            containers = subprocess.run(['docker', 'ps', '-a', '--format', '{{.Names}}'],
                check=True, capture_output=True, text=True).stdout.splitlines()
            networks = subprocess.run(['docker', 'network', 'ls', '--format', '{{.Name}}'],
                check=True, capture_output=True, text=True).stdout.splitlines()
            if {store, engine, client}.intersection(containers) or network in networks:
                raise RuntimeError('Image S3 fixture cleanup could not be confirmed')
    return runtime


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk-dir', required=True)
    parser.add_argument('--engine-artifact')
    arguments = parser.parse_args()
    main(arguments.sdk_dir, arguments.engine_artifact)
