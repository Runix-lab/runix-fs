"""Offline local engine/object backup, original teardown, and fresh restore.

An explicit --engine-artifact uses the verified non-root image without build mounts.
"""
import argparse
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from local_s3_smoke import OBJECT_IMAGE, SDK_IMAGE, TOOL_IMAGE


def main(sdk_dir, engine_artifact=None):
    sdk = Path(sdk_dir).resolve(strict=True)
    if not (sdk / 'boto3').is_dir():
        raise ValueError('Existing boto3 SDK directory required')
    image_fixture = None
    if engine_artifact is not None:
        from image_engine_fixture import ImageEngineFixture
        image_fixture = ImageEngineFixture(engine_artifact)
    fixture = Path(__file__).resolve().parent
    def docker(*args, timeout=30, check=True, **kwargs):
        return subprocess.run(['docker', *args], timeout=timeout, check=check,
                              text=True, **kwargs)
    def inventory():
        containers = docker('ps', '-a', '--format', '{{.Names}}', capture_output=True).stdout.splitlines()
        networks = docker('network', 'ls', '--format', '{{.Name}}', capture_output=True).stdout.splitlines()
        return set(containers), set(networks)
    for image in ((OBJECT_IMAGE, SDK_IMAGE) if image_fixture else (TOOL_IMAGE, OBJECT_IMAGE, SDK_IMAGE)):
        docker('image', 'inspect', image, stdout=subprocess.DEVNULL)
    if not image_fixture:
        docker('volume', 'inspect', 'runix-fs-marketplace-target', stdout=subprocess.DEVNULL)
    runtime = Path(tempfile.mkdtemp(prefix='runix-backup-smoke-'))
    runtime.chmod(0o700)
    print('Local synthetic evidence directory:', runtime, flush=True)
    envfile = runtime / 'fixture.env'
    prefix = 'runix-backup-smoke-' + uuid.uuid4().hex[:12]
    environments = []
    for label in ('original', 'restore'):
        folder = runtime / label
        folder.mkdir(mode=0o700)
        network = prefix + '-' + label
        environments.append(dict(folder=folder, network=network, store=network + '-store',
                                 engine=network + '-engine', client=network + '-client'))
    original, restore = environments
    evidence = {'scope': 'local-offline-synthetic-backup'}
    def create_store(env):
        docker('network', 'create', '--internal', env['network'], stdout=subprocess.DEVNULL)
        docker('run', '-d', '--name', env['store'], '--network', env['network'],
               '--network-alias', 'objectstore', '--env-file', str(envfile),
               '--cpus', '1', '--memory', '1g', OBJECT_IMAGE, 'server', '/data',
               '--console-address', ':9001', stdout=subprocess.DEVNULL)
        state = json.loads(docker('inspect', env['store'], capture_output=True).stdout)[0]
        if state['HostConfig'].get('PortBindings') or set(state['NetworkSettings']['Networks']) != {env['network']}:
            raise RuntimeError('Unexpected object-store network exposure')
        if not json.loads(docker('network', 'inspect', env['network'], capture_output=True).stdout)[0]['Internal']:
            raise RuntimeError('Fixture network must be internal')
    def sdk_phase(env, script, phase):
        with (env['folder'] / ('sdk-' + phase + '.out')).open('w') as log:
            docker('run', '--rm', '--name', env['client'], '--network', env['network'],
                   '--env-file', str(envfile), '--env', 'PYTHONPATH=/sdk',
                   '--mount', f"type=bind,source={env['folder']},target=/smoke",
                   '--mount', f'type=bind,source={fixture},target=/fixture,readonly',
                   '--mount', f'type=bind,source={sdk},target=/sdk,readonly',
                   SDK_IMAGE, 'python', '/fixture/' + script, phase,
                   timeout=120, stdout=log, stderr=subprocess.STDOUT)
    def engine(env, script):
        if image_fixture:
            result = image_fixture.run(env['folder'], env['network'], env['engine'], envfile, fixture / script)
            evidence.setdefault('image_runs', []).append(result)
            return
        with (env['folder'] / 'engine.out').open('w') as log:
            docker('run', '--rm', '--name', env['engine'], '--platform', 'linux/amd64',
                   '--network', env['network'], '--env-file', str(envfile), '--cpus', '2', '--memory', '6g',
                   '--mount', 'type=volume,source=runix-fs-marketplace-target,target=/build,readonly',
                   '--mount', f"type=bind,source={env['folder']},target=/smoke",
                   '--mount', f'type=bind,source={fixture},target=/fixture,readonly',
                   TOOL_IMAGE, 'timeout', '420', 'bash', '/fixture/' + script,
                   timeout=480, stdout=log, stderr=subprocess.STDOUT)
    def remove(env, strict):
        docker('rm', '-fv', env['engine'], env['client'], env['store'], check=False,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        docker('network', 'rm', env['network'], check=False,
               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if strict:
            containers, networks = inventory()
            if containers & {env[key] for key in ('engine', 'client', 'store')} or env['network'] in networks:
                raise RuntimeError('Original environment is not removed; refusing restore')
    try:
        descriptor = os.open(envfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w') as output:
            secret = secrets.token_hex(24)
            output.write('MINIO_ROOT_USER=runixbackupfixture\nAWS_ACCESS_KEY_ID=runixbackupfixture\n'
                         f'MINIO_ROOT_PASSWORD={secret}\nAWS_SECRET_ACCESS_KEY={secret}\n'
                         'AWS_EC2_METADATA_DISABLED=true\n')
        create_store(original)
        sdk_phase(original, 'local_s3_fixture.py', 'seed')
        engine(original, 'local_s3_engine_smoke.sh')
        sdk_phase(original, 'local_s3_fixture.py', 'verify-upload')
        containers, _ = inventory()
        if original['engine'] in containers:
            raise RuntimeError('Original engine still exists; refusing live DB copy')
        sdk_phase(original, 'local_backup_fixture.py', 'export')
        for directory in ('data', 'backup'):
            shutil.copytree(original['folder'] / directory, restore['folder'] / directory)
        for name in ('cluster.toml', 'source.bin', 'upload.bin'):
            shutil.copy2(original['folder'] / name, restore['folder'] / name)
        evidence['object_manifest'] = json.loads((restore['folder'] / 'backup/manifest.json').read_text())
        remove(original, strict=True)
        evidence['original_removed_before_restore'] = True
        print('PASS: offline backup completed and original resources removed', flush=True)
        create_store(restore)
        sdk_phase(restore, 'local_backup_fixture.py', 'import')
        engine(restore, 'local_restore_engine_smoke.sh')
        sdk_phase(restore, 'local_backup_fixture.py', 'verify-new')
        hashes = {}
        for name in ('source.bin', 'restored-source.bin', 'upload.bin', 'restored-upload.bin',
                     'new.bin', 'new-read.bin', 'new-s3.bin'):
            data = (restore['folder'] / name).read_bytes()
            if len(data) != 4 * 1024 * 1024:
                raise RuntimeError('Unexpected restored payload size')
            hashes[name] = hashlib.sha256(data).hexdigest()
        if (hashes['source.bin'] != hashes['restored-source.bin']
                or hashes['upload.bin'] != hashes['restored-upload.bin']
                or len({hashes[key] for key in ('new.bin', 'new-read.bin', 'new-s3.bin')}) != 1):
            raise RuntimeError('Restored payload comparison failed')
        evidence['sha256'] = hashes
        evidence['binary_hashes'] = (restore['folder'] / 'binary-hashes.txt').read_text()
        print('PASS: restored files and new write match independent payloads', flush=True)
    finally:
        failures = []
        for env in environments:
            try:
                remove(env, strict=False)
            except (subprocess.SubprocessError, OSError) as error:
                failures.append(type(error).__name__)
        envfile.unlink(missing_ok=True)
        containers, networks = inventory()
        owned = {env[key] for env in environments for key in ('engine', 'client', 'store')}
        if failures or containers & owned or networks & {env['network'] for env in environments}:
            raise RuntimeError('Backup fixture cleanup could not be confirmed')
    evidence['cleanup'] = 'verified_removed'
    (runtime / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print('PASS: backup/restore test resources removed', flush=True)
    return runtime


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk-dir', required=True)
    parser.add_argument('--engine-artifact')
    arguments = parser.parse_args()
    main(arguments.sdk_dir, arguments.engine_artifact)
