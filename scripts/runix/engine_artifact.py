"""Offline source-pinned local engine image builder and actual runtime gate.

No registry push, AWS call, public listener or commercial readiness claim.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import struct
import subprocess
import tempfile
import uuid
from pathlib import Path

from local_s3_smoke import TOOL_IMAGE

VOLUMES = ('runix-fs-marketplace-target', 'runix-fs-marketplace-cargo', 'runix-fs-marketplace-rustup')
BUILD_NAME = 'runix-fs-artifact-build'
SOURCE_URL = 'https://github.com/Runix-lab/runix-fs'
BINARIES = ('curvine-server', 'curvine-cli')
BUILD_SCRIPT = '''
export PATH=/cargo/bin:$PATH
unset BUILD_VERSION
rustc --version > /artifact/compiler.txt
git rev-parse HEAD > /artifact/source.txt
git diff --quiet
cargo build --locked --offline --jobs 2 -p curvine-server -p curvine-cli
for binary in curvine-server curvine-cli; do
    install -m 0755 /build/target/debug/$binary /artifact/$binary
    /artifact/$binary --version-json > /artifact/$binary.version.json
 done
git diff --quiet
'''


def command(args, **kwargs):
    return subprocess.run(args, check=True, timeout=60, capture_output=True, text=True, **kwargs)


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')
    path.chmod(0o600)


def mount_path(path):
    if not Path(path).is_absolute() or any(char in str(path) for char in (',', '\n', '\r', '\0')):
        raise ValueError('Absolute unambiguous mount path required')
    return str(path)


def file_digest(path, elf=False):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= 2 * 1024**3:
            raise ValueError('Bounded regular artifact required')
        with os.fdopen(descriptor, 'rb', closefd=False) as source:
            first = source.read(64)
            if elf and (len(first) < 20 or first[:6] != b'\x7fELF\x02\x01'
                        or struct.unpack('<H', first[18:20])[0] != 62 or not info.st_mode & 0o111):
                raise ValueError('Executable ELF64 little-endian x86-64 required')
            digest = hashlib.sha256(first)
            for chunk in iter(lambda: source.read(1024**2), b''):
                digest.update(chunk)
        return {'sha256': digest.hexdigest(), 'bytes': info.st_size}
    finally:
        os.close(descriptor)


def snapshot(repo, source, ref):
    if not re.fullmatch(r'[a-f0-9]{40}', ref):
        raise ValueError('Full immutable source commit required')
    actual = command(['git', '-C', str(repo), 'rev-parse', '--verify', ref + '^{commit}']).stdout.strip()
    if actual != ref:
        raise ValueError('Source commit differs')
    command(['git', '-c', 'core.hooksPath=/dev/null', 'clone', '--no-hardlinks', '--no-checkout', '--', str(repo), str(source)])
    command(['git', '-C', str(source), '-c', 'core.hooksPath=/dev/null', 'checkout', '--detach', ref])
    if ((source / '.git/objects/info/alternates').exists()
            or command(['git', '-C', str(source), 'status', '--porcelain']).stdout):
        raise ValueError('Independent clean source snapshot required')
    return command(['git', '-C', str(source), 'rev-parse', 'HEAD^{tree}']).stdout.strip()


def build_command(source, output, run_id):
    source, output = mount_path(source), mount_path(output)
    args = ['docker', 'run', '--name', BUILD_NAME, '--pull', 'never', '--platform', 'linux/amd64',
            '--network', 'none', '--cpus', '2', '--memory', '6g', '--label', 'io.runix.artifact=' + run_id,
            '--workdir', '/workspace', '--mount', f'type=bind,source={source},target=/workspace,readonly',
            '--mount', f'type=bind,source={output},target=/artifact']
    for name, target in zip(VOLUMES, ('/build', '/cargo', '/rustup')):
        args += ['--mount', f'type=volume,source={name},target={target}']
    for key, value in {'CARGO_HOME': '/cargo', 'RUSTUP_HOME': '/rustup', 'RUSTUP_TOOLCHAIN': '1.98',
                       'RUSTUP_AUTO_INSTALL': '0', 'CARGO_TARGET_DIR': '/build/target', 'CARGO_NET_OFFLINE': 'true',
                       'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'safe.directory',
                       'GIT_CONFIG_VALUE_0': '/workspace', 'GIT_OPTIONAL_LOCKS': '0'}.items():
        args += ['--env', key + '=' + value]
    return args + ['--entrypoint', '/bin/bash', TOOL_IMAGE, '-euo', 'pipefail', '-c', BUILD_SCRIPT]


def receipt(source, output, revision, tree):
    if (output / 'source.txt').read_text().strip() != revision:
        raise ValueError('Actual builder source mismatch')
    compiler = (output / 'compiler.txt').read_text().strip()
    if not re.fullmatch(r'rustc 1\.98\.\d+ \([0-9a-f]+ \d{4}-\d{2}-\d{2}\)', compiler):
        raise ValueError('Unexpected actual Rust toolchain')
    binaries = {}
    for name in BINARIES:
        binaries[name] = file_digest(output / name, elf=True)
        version = component_version(output / (name + '.version.json'), name.removeprefix('curvine-'), revision)
        binaries[name]['version'] = version
    if any(binaries[name]['version'][field] != binaries[BINARIES[0]]['version'][field]
           for name in BINARIES for field in ('protocol_version', 'min_protocol_version')):
        raise ValueError('Component protocols differ')
    return {'schema': 1, 'source': SOURCE_URL, 'source_commit': revision, 'source_tree': tree,
            'builder_image': TOOL_IMAGE, 'platform': 'linux/amd64', 'compiler': compiler,
            'cargo_lock': file_digest(source / 'Cargo.lock'), 'binaries': binaries,
            'production_release': False, 'bit_reproducibility_verified': False}


def component_version(path, component, revision):
    raw = path.read_bytes()
    if len(raw) > 4096:
        raise ValueError('Bounded version metadata required')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate version field')
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid JSON constant')))
    if (not isinstance(value, dict) or set(value) != {'component', 'release_version', 'git_commit',
            'git_tag', 'git_branch', 'protocol_version', 'min_protocol_version', 'capabilities'}
            or value.get('component') != component
            or not isinstance(value.get('git_commit'), str)
            or not re.fullmatch(r'[a-f0-9]{7,40}', value['git_commit'])
            or not revision.startswith(value['git_commit'])
            or any(type(value.get(key)) is not int for key in ('protocol_version', 'min_protocol_version'))
            or not 1 <= value['min_protocol_version'] <= value['protocol_version']):
        raise ValueError('Component source/protocol identity mismatch')
    for key in ('release_version', 'git_tag', 'git_branch'):
        item = value.get(key)
        if (not isinstance(item, str) or len(item) > 255 or any(ord(char) < 32 for char in item)
                or 'dirty' in item.lower() or (key == 'release_version' and not item)):
            raise ValueError('Invalid component version metadata')
    caps = value.get('capabilities')
    if (not isinstance(caps, list) or len(caps) > 32
            or any(not isinstance(cap, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', cap) for cap in caps)):
        raise ValueError('Invalid component capabilities')
    return value


def dockerfile():
    return f'''FROM {TOOL_IMAGE}
LABEL org.opencontainers.image.source="{SOURCE_URL}"
COPY curvine-server curvine-cli /opt/runix/bin/
COPY LICENSE NOTICE README.upstream.md build-receipt.json /usr/share/doc/runix-fs/
RUN chmod 0755 /opt/runix/bin/curvine-server /opt/runix/bin/curvine-cli && mkdir -p /smoke /var/lib/runix && chown 1000:1000 /smoke /var/lib/runix
USER 1000:1000
WORKDIR /var/lib/runix
ENTRYPOINT ["/opt/runix/bin/curvine-server"]
CMD ["--help"]
'''


def validate_image(state, image_id, revision):
    config = state['Config']
    if (not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id) or state['Id'] != image_id
            or (state['Os'], state['Architecture']) != ('linux', 'amd64')
            or config['User'] != '1000:1000' or config.get('ExposedPorts') or config.get('Volumes')
            or config['Entrypoint'] != ['/opt/runix/bin/curvine-server'] or config['Cmd'] != ['--help']
            or config['Labels'].get('org.opencontainers.image.revision') != revision
            or config['Labels'].get('org.opencontainers.image.source') != SOURCE_URL):
        raise ValueError('Image identity/runtime configuration mismatch')


def validate_smoke(state, name, volume, image_id, script):
    host = state['HostConfig']
    mounts = state['Mounts']
    if (state['Name'] != '/' + name or state['Image'] != image_id
            or state['Config']['User'] != '1000:1000' or host['NetworkMode'] != 'none'
            or host.get('PortBindings') or host['Privileged'] or not host['ReadonlyRootfs']
            or 'ALL' not in host.get('CapDrop', [])
            or 'no-new-privileges' not in host.get('SecurityOpt', []) or len(mounts) != 2):
        raise ValueError('Unsafe smoke boundary')
    by_path = {mount['Destination']: mount for mount in mounts}
    if (set(by_path) != {'/smoke', '/run-smoke.sh'}
            or by_path['/smoke']['Type'] != 'volume' or by_path['/smoke'].get('Name') != volume
            or not by_path['/smoke']['RW'] or by_path['/run-smoke.sh']['Type'] != 'bind'
            or by_path['/run-smoke.sh']['Source'] != str(script) or by_path['/run-smoke.sh']['RW']):
        raise ValueError('Unexpected smoke mounts')


def owned_cleanup(containers, volume=None):
    """Remove exactly known-owned resources, attempt all, confirm fresh inventory."""
    failures = []
    for name in containers:
        try:
            command(['docker', 'rm', '-f', name])
        except Exception:
            failures.append('container')
    if volume is not None:
        try:
            command(['docker', 'volume', 'rm', volume])
        except Exception:
            failures.append('volume')
    try:
        remaining = set(command(['docker', 'ps', '-a', '--format', '{{.Names}}']).stdout.splitlines())
        volumes = set(command(['docker', 'volume', 'ls', '--format', '{{.Name}}']).stdout.splitlines())
        if remaining.intersection(containers) or (volume is not None and volume in volumes):
            failures.append('inventory')
    except Exception:
        failures.append('inventory')
    if failures:
        raise RuntimeError('Owned artifact cleanup could not be confirmed') from None


def final_cleanup(containers, volume, image_tag):
    try:
        if containers or volume:
            owned_cleanup(containers, volume)
    finally:
        if image_tag:
            command(['docker', 'image', 'rm', image_tag])


def main(repo, revision):
    repo = Path(repo).resolve(strict=True)
    runtime = Path(tempfile.mkdtemp(prefix='runix-engine-artifact-'))
    runtime.chmod(0o700)
    run_id = uuid.uuid4().hex[:12]
    source, output = runtime / 'source', runtime / 'context'
    output.mkdir(mode=0o700)
    smoke, volume = 'runix-artifact-smoke-' + run_id, 'runix-artifact-data-' + run_id
    image_tag = 'runix-fs-local:' + revision[:12] + '-' + run_id
    containers, own_volume, own_image = [], None, False
    print('Artifact operation directory:', runtime, flush=True)
    write_json(runtime / 'operation.json', {'source_commit': revision, 'build_container': BUILD_NAME,
        'smoke_container': smoke, 'smoke_volume': volume, 'image_tag': image_tag, 'run_id': run_id})
    try:
        for cached in (TOOL_IMAGE,):
            state = json.loads(command(['docker', 'image', 'inspect', cached]).stdout)[0]
            if (state['Os'], state['Architecture']) != ('linux', 'amd64'):
                raise ValueError('Cached amd64 builder required')
        for name in VOLUMES:
            command(['docker', 'volume', 'inspect', name])
            if command(['docker', 'ps', '-q', '--filter', 'volume=' + name]).stdout.strip():
                raise RuntimeError('An existing container is using the build caches')
        if command(['docker', 'ps', '-aq', '--filter', 'name=^/' + BUILD_NAME + '$']).stdout.strip():
            raise RuntimeError('An existing artifact builder must be inspected before continuing')
        tree = snapshot(repo, source, revision)
        print('Building captured source with offline cached dependencies.', flush=True)
        # Fixed name rejects concurrent instances. Only adopt ownership after
        # verifying the unique label, including an interrupted/failed docker run.
        try:
            with (runtime / 'build.log').open('w') as log:
                subprocess.run(build_command(source, output, run_id), check=True, timeout=7200,
                               stdout=log, stderr=subprocess.STDOUT)
        finally:
            state = json.loads(command(['docker', 'inspect', BUILD_NAME]).stdout)[0]
            if state['Config']['Labels'].get('io.runix.artifact') == run_id:
                containers.append(BUILD_NAME)
        build = receipt(source, output, revision, tree)
        for name in ('LICENSE', 'NOTICE', 'README.upstream.md'):
            shutil.copyfile(source / name, output / name)
        write_json(output / 'build-receipt.json', build)
        (output / 'Dockerfile').write_text(dockerfile())
        print('Building local non-root image from fresh binaries.', flush=True)
        try:
            with (runtime / 'image-build.log').open('w') as log:
                subprocess.run(['docker', 'build', '--pull=false', '--network=none', '--platform=linux/amd64',
                    '--label', 'org.opencontainers.image.revision=' + revision, '--label', 'io.runix.artifact=' + run_id,
                    '--iidfile', str(runtime / 'image-id'), '--tag', image_tag, str(output)],
                    check=True, timeout=600, stdout=log, stderr=subprocess.STDOUT)
        finally:
            # A failed CLI observation may still have created an image. Adopt
            # only the unique operation label, never a same-name foreign image.
            try:
                built = json.loads(command(['docker', 'image', 'inspect', image_tag]).stdout)[0]
                own_image = built['Config']['Labels'].get('io.runix.artifact') == run_id
            except Exception:
                pass
        if not own_image:
            raise RuntimeError('Built image ownership could not be established')
        image_id = built['Id']
        build_reference = (runtime / 'image-id').read_text().strip()
        state = json.loads(command(['docker', 'image', 'inspect', build_reference]).stdout)[0]
        if state['Id'] != image_id:
            raise ValueError('Build output and local image differ')
        validate_image(state, image_id, revision)
        try:
            command(['docker', 'volume', 'create', '--label', 'io.runix.artifact=' + run_id, volume])
        finally:
            try:
                info = json.loads(command(['docker', 'volume', 'inspect', volume]).stdout)[0]
                if info['Labels'].get('io.runix.artifact') == run_id:
                    own_volume = volume
            except Exception:
                pass
        if own_volume is None:
            raise RuntimeError('Fresh smoke volume ownership mismatch')
        script = (repo / 'scripts/runix/local_engine_smoke.sh').resolve(strict=True)
        mount_path(script)
        script_digest = file_digest(script)
        try:
            command(['docker', 'run', '-d', '--name', smoke, '--pull', 'never', '--platform', 'linux/amd64',
                '--label', 'io.runix.artifact=' + run_id,
                '--network', 'none', '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                '--pids-limit', '512', '--cpus', '2', '--memory', '4g', '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=64m',
                '--mount', 'type=volume,source=' + volume + ',target=/smoke',
                '--mount', f'type=bind,source={script},target=/run-smoke.sh,readonly',
                '--env', 'RUNIX_ENGINE_BIN_DIR=/opt/runix/bin', '--entrypoint', '/bin/bash', image_id,
                '-euo', 'pipefail', '-c', 'id -u > /smoke/runtime-uid.txt; exec bash /run-smoke.sh'])
        finally:
            try:
                info = json.loads(command(['docker', 'inspect', smoke]).stdout)[0]
                if info['Config']['Labels'].get('io.runix.artifact') == run_id:
                    containers.append(smoke)
            except Exception:
                pass
        if smoke not in containers:
            raise RuntimeError('Smoke container ownership mismatch')
        validate_smoke(json.loads(command(['docker', 'inspect', smoke]).stdout)[0], smoke, volume, image_id, script)
        print('Running actual isolated image write/read and crash-recovery gate.', flush=True)
        result = subprocess.run(['docker', 'wait', smoke], check=True, timeout=360, capture_output=True, text=True)
        with (runtime / 'smoke.log').open('w') as log:
            subprocess.run(['docker', 'logs', smoke], check=True, timeout=30, stdout=log, stderr=subprocess.STDOUT)
        if result.stdout.strip() != '0':
            raise RuntimeError('Actual image engine smoke failed')
        evidence = runtime / 'smoke'
        command(['docker', 'cp', smoke + ':/smoke/.', str(evidence)])
        payloads = [file_digest(evidence / name) for name in ('payload.bin', 'read-before.bin', 'read-after.bin')]
        if (any(item != payloads[0] for item in payloads) or payloads[0]['bytes'] != 4194304
                or file_digest(script) != script_digest
                or (evidence / 'runtime-uid.txt').read_text().strip() != '1000'):
            raise RuntimeError('Actual data/identity comparison failed')
        owned_cleanup(containers, own_volume)
        containers, own_volume = [], None
        write_json(runtime / 'artifact.json', dict(build, image_id=image_id, image_tag=image_tag, smoke_script=script_digest,
            smoke={'bytes': payloads[0]['bytes'], 'sha256': payloads[0]['sha256'], 'runtime_uid': 1000,
                   'actual_write_read_restart': True, 'owned_resources_removed': True}))
        own_image = False  # Retain the successfully verified local artifact.
        print(json.dumps({'artifact': str(runtime / 'artifact.json'), 'image_id': image_id,
                          'actual_write_read_restart': True}), flush=True)
    finally:
        final_cleanup(containers, own_volume, image_tag if own_image else None)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--source-commit', required=True)
    arguments = parser.parse_args()
    try:
        main(arguments.repo, arguments.source_commit)
    except Exception:
        raise SystemExit('Artifact operation failed; inspect private operation logs. No passing receipt issued.') from None
