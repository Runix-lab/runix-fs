"""Actual two-boundary local integration; no AWS, public ports or provisioning API."""
import argparse
import json
import os
import secrets
import subprocess
import tempfile
import uuid
from pathlib import Path

from local_s3_smoke import OBJECT_IMAGE, SDK_IMAGE, TOOL_IMAGE


def main(sdk_dir):
    sdk = Path(sdk_dir).resolve(strict=True)
    if not (sdk / 'boto3').is_dir():
        raise ValueError('Existing boto3 SDK directory required')
    fixture = Path(__file__).resolve().parent
    def docker(*args, timeout=30, check=True, **kwargs):
        return subprocess.run(['docker', *args], timeout=timeout, check=check,
                              text=True, **kwargs)
    for image in (TOOL_IMAGE, OBJECT_IMAGE, SDK_IMAGE):
        docker('image', 'inspect', image, stdout=subprocess.DEVNULL)
    docker('volume', 'inspect', 'runix-fs-marketplace-target', stdout=subprocess.DEVNULL)
    runtime = Path(tempfile.mkdtemp(prefix='runix-tenant-smoke-'))
    runtime.chmod(0o700)
    print('Local synthetic evidence directory:', runtime, flush=True)
    prefix = 'runix-tenant-smoke-' + uuid.uuid4().hex[:12]
    tenants = []
    for label in ('a', 'b'):
        folder = runtime / label
        folder.mkdir(mode=0o700)
        network = prefix + '-' + label
        tenants.append(dict(label=label, folder=folder, network=network,
                            store=network + '-store', client=network + '-client',
                            engine=network + '-engine', access='runixfixture' + label,
                            secret=secrets.token_hex(24), envfile=folder / 'fixture.env',
                            probe_envfile=folder / 'probe.env'))
    evidence = {'scope': 'local-docker-only', 'tenants': {}}
    try:
        for tenant in tenants:
            descriptor = os.open(tenant['envfile'], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w') as output:
                output.write(f"MINIO_ROOT_USER={tenant['access']}\nMINIO_ROOT_PASSWORD={tenant['secret']}\n"
                             f"AWS_ACCESS_KEY_ID={tenant['access']}\nAWS_SECRET_ACCESS_KEY={tenant['secret']}\n"
                             'AWS_EC2_METADATA_DISABLED=true\n')
            docker('network', 'create', '--internal', tenant['network'], stdout=subprocess.DEVNULL)
            docker('run', '-d', '--name', tenant['store'], '--network', tenant['network'],
                   '--network-alias', 'objectstore', '--env-file', str(tenant['envfile']),
                   '--cpus', '1', '--memory', '1g', OBJECT_IMAGE, 'server', '/data',
                   '--console-address', ':9001', stdout=subprocess.DEVNULL)
            state = json.loads(docker('inspect', tenant['store'], capture_output=True).stdout)[0]
            if state['HostConfig'].get('PortBindings'):
                raise RuntimeError('Unexpected host port exposure')
            addresses = state['NetworkSettings']['Networks']
            if set(addresses) != {tenant['network']}:
                raise RuntimeError('Unexpected object-store network attachment')
            tenant['ip'] = addresses[tenant['network']]['IPAddress']
            networks = json.loads(docker('network', 'inspect', tenant['network'], capture_output=True).stdout)
            if not networks[0]['Internal']:
                raise RuntimeError('Network is not internal')

        def sdk_phase(tenant, script, phase=None):
            envfile = tenant['probe_envfile'] if script == 'local_tenant_probe.py' else tenant['envfile']
            command = ['run', '--rm', '--name', tenant['client'], '--network', tenant['network'],
                       '--env-file', str(envfile), '--env', 'PYTHONPATH=/sdk',
                       '--mount', f"type=bind,source={tenant['folder']},target=/smoke",
                       '--mount', f'type=bind,source={fixture},target=/fixture,readonly',
                       '--mount', f'type=bind,source={sdk},target=/sdk,readonly',
                       SDK_IMAGE, 'python', '/fixture/' + script]
            if phase:
                command.append(phase)
            with (tenant['folder'] / ('sdk-' + (phase or 'probe') + '.out')).open('w') as log:
                docker(*command, timeout=90, stdout=log, stderr=subprocess.STDOUT)

        for tenant in tenants:
            sdk_phase(tenant, 'local_s3_fixture.py', 'seed')
        for index, tenant in enumerate(tenants):
            peer = tenants[1 - index]
            descriptor = os.open(tenant['probe_envfile'], os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, 'w') as output:
                output.write(tenant['envfile'].read_text())
                output.write(f"RUNIX_PEER_IP={peer['ip']}\nRUNIX_PEER_ACCESS={peer['access']}\n"
                             f"RUNIX_PEER_SECRET={peer['secret']}\n")
            sdk_phase(tenant, 'local_tenant_probe.py')
            with (tenant['folder'] / 'engine.out').open('w') as log:
                docker('run', '--rm', '--name', tenant['engine'], '--platform', 'linux/amd64',
                       '--network', tenant['network'], '--env-file', str(tenant['envfile']),
                       '--cpus', '2', '--memory', '6g',
                       '--mount', 'type=volume,source=runix-fs-marketplace-target,target=/build,readonly',
                       '--mount', f"type=bind,source={tenant['folder']},target=/smoke",
                       '--mount', f'type=bind,source={fixture},target=/fixture,readonly',
                       TOOL_IMAGE, 'timeout', '420', 'bash', '/fixture/local_s3_engine_smoke.sh',
                       timeout=480, stdout=log, stderr=subprocess.STDOUT)
            sdk_phase(tenant, 'local_s3_fixture.py', 'verify-upload')
            sdk_phase(tenant, 'local_s3_fixture.py', 'evidence')
            payloads = json.loads((tenant['folder'] / 'evidence.json').read_text())
            for original, copies in (('source.bin', ('read-before.bin', 'read-after.bin')),
                                     ('upload.bin', ('s3-upload.bin', 'upload-after.bin'))):
                if any(payloads[copy] != payloads[original] for copy in copies):
                    raise RuntimeError('Payload evidence mismatch')
            evidence['tenants'][tenant['label']] = {
                'network_and_credentials': 'passed', 'payloads': payloads,
                'binary_hashes': (tenant['folder'] / 'binary-hashes.txt').read_text(),
            }
            print(f"PASS: boundary {tenant['label']} isolation, real engine IO and crash recovery", flush=True)
        for name in ('source.bin', 'upload.bin'):
            if evidence['tenants']['a']['payloads'][name] == evidence['tenants']['b']['payloads'][name]:
                raise RuntimeError('Independent boundaries unexpectedly have identical payloads')
        evidence['independent_same_object_paths'] = 'passed'
    finally:
        cleanup_errors = []
        for tenant in tenants:
            try:
                docker('rm', '-fv', tenant['engine'], tenant['client'], tenant['store'],
                       check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                docker('network', 'rm', tenant['network'], check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except (subprocess.SubprocessError, OSError) as error:
                cleanup_errors.append(type(error).__name__)
            finally:
                tenant['envfile'].unlink(missing_ok=True)
                tenant['probe_envfile'].unlink(missing_ok=True)
        # Successful fresh inventories are required; an unavailable daemon is
        # not proof that a failed removal actually cleaned up resources.
        names = set(docker('ps', '-a', '--format', '{{.Names}}', capture_output=True).stdout.splitlines())
        networks = set(docker('network', 'ls', '--format', '{{.Name}}', capture_output=True).stdout.splitlines())
        owned = {tenant[key] for tenant in tenants for key in ('store', 'engine', 'client')}
        if cleanup_errors or names & owned or networks & {tenant['network'] for tenant in tenants}:
            raise RuntimeError('Owned test resources could not be confirmed removed')
    evidence['cleanup'] = 'verified_removed'
    (runtime / 'evidence.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print('PASS: independent data and all owned containers/networks removed', flush=True)
    return runtime


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk-dir', required=True)
    main(parser.parse_args().sdk_dir)
