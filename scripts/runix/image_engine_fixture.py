"""Actual pinned-image engine runner for private synthetic S3/restore fixtures.

Not a provisioner. Preparation root never runs the filesystem service.
"""
import json
import re
import stat
import subprocess
import uuid
from pathlib import Path

import engine_artifact as artifact


class ImageEngineFixture:
    def __init__(self, receipt):
        path = Path(receipt).resolve(strict=True)
        if not path.is_file() or path.stat().st_size > 65536:
            raise ValueError('Bounded artifact receipt required')
        with path.open('rb') as source:
            raw = source.read(65537)
        if len(raw) > 65536:
            raise ValueError('Bounded artifact receipt required')
        self.build = json.loads(raw)
        self.image = self.build['image_id']
        if (not re.fullmatch(r'[a-f0-9]{40}', self.build['source_commit'])
                or self.build.get('schema') != 1
                or self.build.get('production_release') is not False
                or self.build.get('smoke', {}).get('actual_write_read_restart') is not True
                or self.build['smoke'].get('owned_resources_removed') is not True):
            raise ValueError('Verified local artifact receipt required')
        state = json.loads(artifact.command(['docker', 'image', 'inspect', self.image]).stdout)[0]
        artifact.validate_image(state, self.image, self.build['source_commit'])

    @staticmethod
    def _inputs(folder, restore):
        names = ['source.bin', 'upload.bin'] + (['cluster.toml', 'data'] if restore else [])
        if restore:
            for required in ('data/meta', 'data/journal', 'data/worker'):
                if not (folder / required).is_dir():
                    raise ValueError('Complete stopped-state fixture required')
        for name in names:
            path = folder / name
            if name != 'data' and not path.is_file():
                raise ValueError('Regular fixture payload/config required')
            candidates = [path, *path.rglob('*')] if path.is_dir() else [path]
            for item in candidates:
                mode = item.lstat().st_mode
                if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                    raise ValueError('Only regular stopped-state fixture inputs allowed')
        return names

    def _adopt(self, name, label, containers):
        state = json.loads(artifact.command(['docker', 'inspect', name]).stdout)[0]
        if state['Config']['Labels'].get('io.runix.artifact') != label:
            raise RuntimeError('Foreign fixture container')
        containers.append(name)
        return state

    def run(self, folder, network, name, envfile, script):
        folder, script = Path(folder).resolve(strict=True), Path(script).resolve(strict=True)
        if script.name not in ('local_s3_engine_smoke.sh', 'local_restore_engine_smoke.sh'):
            raise ValueError('Known synthetic engine script required')
        if (folder / 'image-execution.json').exists():
            raise ValueError('Fixture folder already has image execution evidence')
        inputs = self._inputs(folder, script.name == 'local_restore_engine_smoke.sh')
        net = json.loads(artifact.command(['docker', 'network', 'inspect', network]).stdout)[0]
        if net.get('Internal') is not True or net.get('Name') != network:
            raise ValueError('Actual internal fixture network required')
        digest = artifact.file_digest(script)
        label = uuid.uuid4().hex[:12]
        prep, volume = name + '-prepare', name + '-data'
        containers, owned_volume, state, execution_error = [], None, None, None
        artifact.write_json(folder / 'image-operation.json', dict(image_id=self.image,
            source_commit=self.build['source_commit'], container=name, prepare_container=prep,
            volume=volume, run_id=label, network=network, script=digest))
        try:
            try:
                artifact.command(['docker', 'volume', 'create', '--label', 'io.runix.artifact=' + label, volume])
            finally:
                vol = json.loads(artifact.command(['docker', 'volume', 'inspect', volume]).stdout)[0]
                if vol['Labels'].get('io.runix.artifact') != label:
                    raise RuntimeError('Foreign fixture volume')
                owned_volume = volume
            try:
                artifact.command(['docker', 'run', '-d', '--name', prep, '--pull', 'never',
                    '--platform', 'linux/amd64', '--label', 'io.runix.artifact=' + label,
                    '--user', '0:0', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                    '--cap-add', 'CHOWN', '--cap-add', 'DAC_OVERRIDE', '--security-opt', 'no-new-privileges',
                    '--memory', '128m', '--pids-limit', '32', '--mount',
                    'type=volume,source=' + volume + ',target=/smoke', '--entrypoint', '/bin/bash',
                    self.image, '-ec', 'exec sleep 600'])
            finally:
                self._adopt(prep, label, containers)
            for item in inputs:
                artifact.command(['docker', 'cp', str(folder / item), prep + ':/smoke/' + item])
            artifact.command(['docker', 'exec', '--user', '0:0', prep,
                              '/bin/chown', '-R', '1000:1000', '/smoke'])
            artifact.owned_cleanup([prep])
            containers.remove(prep)
            wrapper = '''sha256sum /run-smoke.sh > /smoke/image-script.sha256
read -r actual_script_digest script_label < /smoke/image-script.sha256
test "$actual_script_digest" = "$RUNIX_EXPECTED_SMOKE_SHA256"
id -u > /smoke/runtime-uid.txt
sha256sum /opt/runix/bin/curvine-server /opt/runix/bin/curvine-cli > /smoke/image-binaries.sha256
/opt/runix/bin/curvine-server --version-json > /smoke/curvine-server.version.json
/opt/runix/bin/curvine-cli --version-json > /smoke/curvine-cli.version.json
exec timeout 420 bash /run-smoke.sh'''
            try:
                artifact.command(['docker', 'create', '--name', name, '--pull', 'never',
                    '--platform', 'linux/amd64', '--label', 'io.runix.artifact=' + label,
                    '--network', network, '--read-only', '--cap-drop', 'ALL',
                    '--security-opt', 'no-new-privileges', '--memory', '4g', '--cpus', '2',
                    '--pids-limit', '512', '--tmpfs', '/tmp:rw,nosuid,nodev,noexec,size=64m',
                    '--mount', 'type=volume,source=' + volume + ',target=/smoke',
                    '--mount', 'type=bind,source=' + artifact.mount_path(script) + ',target=/run-smoke.sh,readonly',
                    '--env-file', str(envfile), '--env', 'RUNIX_ENGINE_BIN_DIR=/opt/runix/bin',
                    '--env', 'RUNIX_EXPECTED_SMOKE_SHA256=' + digest['sha256'],
                    '--entrypoint', '/bin/bash', self.image, '-euo', 'pipefail', '-c', wrapper])
            finally:
                state = self._adopt(name, label, containers)
            artifact.validate_smoke(state, name, volume, self.image, script, digest['sha256'], private_network=net)
            with (folder / 'engine.out').open('w') as log:
                subprocess.run(['docker', 'start', '-a', name], check=True, timeout=480,
                               stdout=log, stderr=subprocess.STDOUT)
            state = json.loads(artifact.command(['docker', 'inspect', name]).stdout)[0]
            artifact.validate_smoke(state, name, volume, self.image, script, digest['sha256'], private_network=net)
            if state['State']['Running'] or state['State']['ExitCode'] != 0:
                raise RuntimeError('Actual image S3/restore engine failed')
        except Exception as error:
            execution_error = error
        finally:
            # Preserve diagnostics/state only after stopping this actual engine.
            # No open RocksDB or live worker directory is used as a backup.
            try:
                if name in containers:
                    state = json.loads(artifact.command(['docker', 'inspect', name]).stdout)[0]
                    if state['State']['Running']:
                        artifact.command(['docker', 'kill', name])
                        artifact.command(['docker', 'wait', name])
                        state = json.loads(artifact.command(['docker', 'inspect', name]).stdout)[0]
                    if state['State']['Running']:
                        raise RuntimeError('Refusing to copy live engine state')
                    artifact.command(['docker', 'cp', name + ':/smoke/.', str(folder)])
            finally:
                artifact.owned_cleanup(containers, owned_volume)
        if execution_error is not None:
            raise execution_error
        artifact.validate_execution(folder, self.build, script, digest)
        result = dict(image_id=self.image, source_commit=self.build['source_commit'], runtime_uid=1000,
                      stopped_before_copy=True, owned_resources_removed=True, production_release=False)
        artifact.write_json(folder / 'image-execution.json', result)
        return result
