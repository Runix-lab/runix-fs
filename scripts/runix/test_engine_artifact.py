"""Artifact supply-chain validation and owned-resource failure tests; no Docker."""
import copy
import json
import os
import stat
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import engine_artifact as artifact

REVISION = 'a' * 40
TREE = 'b' * 40
IMAGE = 'sha256:' + 'c' * 64


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.output = self.root / 'source', self.root / 'output'
        self.source.mkdir()
        self.output.mkdir()
        (self.source / 'Cargo.lock').write_bytes(b'synthetic-lock')
        (self.output / 'source.txt').write_text(REVISION)
        (self.output / 'compiler.txt').write_text('rustc 1.98.1 (abcdef012 2026-10-09)')
        header = bytearray(64)
        header[:6] = b'\x7fELF\x02\x01'
        header[18:20] = struct.pack('<H', 62)
        for name in artifact.BINARIES:
            path = self.output / name
            path.write_bytes(header + b'synthetic-not-a-runnable-binary')
            path.chmod(0o755)
            (self.output / (name + '.version.json')).write_text(json.dumps(dict(component=name.removeprefix('curvine-'), release_version='0.2.2', git_commit=REVISION[:7], git_tag='', git_branch='', protocol_version=1, min_protocol_version=1, capabilities=[])))

    def image(self):
        return dict(Id=IMAGE, Os='linux', Architecture='amd64', Config=dict(User='1000:1000',
            Entrypoint=['/opt/runix/bin/curvine-server'], Cmd=['--help'], ExposedPorts=None, Volumes=None,
            Labels={'org.opencontainers.image.revision': REVISION, 'org.opencontainers.image.source': artifact.SOURCE_URL}))

    def smoke(self):
        return dict(Name='/owned', Image=IMAGE, Config={'User': '1000:1000'},
            HostConfig=dict(NetworkMode='none', PortBindings={}, Privileged=False, ReadonlyRootfs=True,
                CapDrop=['ALL'], SecurityOpt=['no-new-privileges']),
            Mounts=[dict(Destination='/smoke', Type='volume', Name='owned-volume', RW=True),
                    dict(Destination='/run-smoke.sh', Type='bind', Source='/fixed/script.sh', RW=False)])

    def test_receipt_pins_actual_source_compiler_and_file_digests(self):
        result = artifact.receipt(self.source, self.output, REVISION, TREE)
        self.assertEqual(result['source_commit'], REVISION)
        self.assertEqual(result['source_tree'], TREE)
        self.assertEqual(result['platform'], 'linux/amd64')
        self.assertEqual(result['binaries']['curvine-cli']['sha256'], artifact.file_digest(self.output / 'curvine-cli')['sha256'])
        self.assertFalse(result['production_release'])
        self.assertFalse(result['bit_reproducibility_verified'])
        self.assertNotIn(str(self.temp.name), json.dumps(result))

    def test_wrong_source_old_or_dirty_binary_and_wrong_compiler_refused(self):
        for name, value in (('source.txt', 'd' * 40), ('compiler.txt', 'rustc 1.92.0 (abcdef 2025-01-01)'),
                            ('curvine-server.version.json', 'old-commit'), ('curvine-cli.version.json', REVISION[:7] + '-dirty')):
            path = self.output / name
            original = path.read_bytes()
            path.write_text(value)
            with self.subTest(name=name), self.assertRaises(ValueError):
                artifact.receipt(self.source, self.output, REVISION, TREE)
            path.write_bytes(original)

    def test_structured_version_claims_not_human_package_output(self):
        path = self.output / 'curvine-cli.version.json'
        original = json.loads(path.read_text())
        for key, value in (('git_commit', 'd' * 7), ('git_commit', 'a' * 6), ('component', 'server'),
                           ('protocol_version', True), ('min_protocol_version', 2),
                           ('git_branch', 'branch-dirty'), ('release_version', ''), ('capabilities', ['bad token']),
                           ('capabilities', ['x'] * 33), ('git_tag', None)):
            path.write_text(json.dumps(dict(original, **{key: value})))
            with self.subTest(key=key), self.assertRaises(ValueError):
                artifact.component_version(path, 'cli', REVISION)
        for raw in ('curvine-cli 0.2.2', '{"component":"cli","component":"cli"}', 'x' * 4097,
                    json.dumps(dict(original, unexpected='extra'))):
            path.write_text(raw)
            with self.assertRaises(ValueError):
                artifact.component_version(path, 'cli', REVISION)
        path.write_text(json.dumps(original))
        self.assertEqual(artifact.component_version(path, 'cli', REVISION)['git_commit'], REVISION[:7])

    def test_server_and_cli_protocol_versions_must_match(self):
        path = self.output / 'curvine-cli.version.json'
        value = json.loads(path.read_text())
        value['protocol_version'] = 2
        path.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            artifact.receipt(self.source, self.output, REVISION, TREE)

    def test_elf_architecture_executable_regular_file_and_symlink_checks(self):
        path = self.output / 'curvine-server'
        original = path.read_bytes()
        for value in (b'', b'not-elf', original[:18] + struct.pack('<H', 183) + original[20:],
                      b'\x7fELF\x01\x01' + original[6:]):
            path.write_bytes(value)
            with self.assertRaises(ValueError):
                artifact.file_digest(path, elf=True)
        path.write_bytes(original)
        path.chmod(0o644)
        with self.assertRaises(ValueError):
            artifact.file_digest(path, elf=True)
        link = self.root / 'binary-link'
        link.symlink_to(path)
        with self.assertRaises(OSError):
            artifact.file_digest(link, elf=True)
        with self.assertRaises(ValueError):
            artifact.file_digest(self.root)

    def test_build_command_is_offline_pinned_and_does_not_mount_actual_repo(self):
        args = artifact.build_command(self.source, self.output, 'owned-id')
        self.assertIn(artifact.TOOL_IMAGE, args)
        self.assertIn('linux/amd64', args)
        self.assertEqual(args[args.index('--network') + 1], 'none')
        self.assertIn(f'type=bind,source={self.source},target=/workspace,readonly', args)
        self.assertIn('CARGO_NET_OFFLINE=true', args)
        self.assertIn('GIT_CONFIG_VALUE_0=/workspace', args)
        self.assertNotIn('safe.directory=*', ' '.join(args))
        self.assertIn('cargo build --locked --offline', args[-1])
        self.assertNotIn('/var/run/docker.sock', ' '.join(args))
        self.assertNotIn('--privileged', args)

    def test_ambiguous_mount_paths_refused(self):
        for path in ('relative', '/tmp/source,readonly', '/tmp/with\nnewline', '/tmp/with\0null'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                artifact.build_command(Path(path), self.output, 'owned')

    def test_snapshot_rejects_nonimmutable_ref_before_any_command(self):
        with patch.object(artifact, 'command') as command:
            for ref in ('HEAD', 'main', 'abc', REVISION + ';evil', 'A' * 40):
                with self.assertRaises(ValueError):
                    artifact.snapshot(self.root, self.source, ref)
            command.assert_not_called()

    def test_snapshot_independent_checkout_and_revision_guard(self):
        destination = self.root / 'snapshot'
        responses = [Mock(stdout=REVISION + '\n'), Mock(stdout=''), Mock(stdout=''), Mock(stdout=''), Mock(stdout=TREE)]
        with patch.object(artifact, 'command', side_effect=responses) as command:
            self.assertEqual(artifact.snapshot(self.root, destination, REVISION), TREE)
        calls = [call.args[0] for call in command.call_args_list]
        self.assertIn('--no-hardlinks', calls[1])
        self.assertIn('--no-checkout', calls[1])
        self.assertIn('--detach', calls[2])
        with patch.object(artifact, 'command', return_value=Mock(stdout='e' * 40)):
            with self.assertRaises(ValueError):
                artifact.snapshot(self.root, destination, REVISION)

    def test_snapshot_refuses_dirty_or_shared_object_source(self):
        destination = self.root / 'snapshot'
        for dirty in (' M source', ''):
            if not dirty:
                alternates = destination / '.git/objects/info'
                alternates.mkdir(parents=True)
                (alternates / 'alternates').write_text('other/source')
            responses = [Mock(stdout=REVISION), Mock(), Mock(), Mock(stdout=dirty)]
            with patch.object(artifact, 'command', side_effect=responses), self.assertRaises(ValueError):
                artifact.snapshot(self.root, destination, REVISION)

    def test_image_requires_digest_architecture_nonroot_labels_and_harmless_default(self):
        artifact.validate_image(self.image(), IMAGE, REVISION)
        for change in ({'Id': 'sha256:' + 'd' * 64}, {'Architecture': 'arm64'}, {'Os': 'windows'}):
            state = self.image()
            state.update(change)
            with self.assertRaises(ValueError):
                artifact.validate_image(state, IMAGE, REVISION)
        for key, value in (('User', '0'), ('Cmd', ['--service', 'master']), ('Entrypoint', ['/bin/sh']),
                           ('ExposedPorts', {'9001/tcp': {}}), ('Volumes', {'/host': {}}), ('Labels', {})):
            state = self.image()
            state['Config'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                artifact.validate_image(state, IMAGE, REVISION)
        with self.assertRaises(ValueError):
            artifact.validate_image(self.image(), 'runix-fs-local:tag', REVISION)

    def test_runtime_refuses_ports_privileges_wrong_identity_or_extra_mounts(self):
        artifact.validate_smoke(self.smoke(), 'owned', 'owned-volume', IMAGE, Path('/fixed/script.sh'))
        changes = [('NetworkMode', 'host'), ('PortBindings', {'9001/tcp': [{'HostPort': '9001'}]}),
                   ('Privileged', True), ('ReadonlyRootfs', False), ('CapDrop', []), ('SecurityOpt', [])]
        for key, value in changes:
            state = self.smoke()
            state['HostConfig'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                artifact.validate_smoke(state, 'owned', 'owned-volume', IMAGE, Path('/fixed/script.sh'))
        for change in ('user', 'image', 'mount', 'rw', 'volume'):
            state = self.smoke()
            if change == 'user': state['Config']['User'] = '0'
            if change == 'image': state['Image'] = 'other'
            if change == 'mount': state['Mounts'].append(dict(Destination='/etc', Type='bind', RW=True))
            if change == 'rw': state['Mounts'][1]['RW'] = True
            if change == 'volume': state['Mounts'][0]['Name'] = 'unrelated-existing'
            with self.subTest(change=change), self.assertRaises(ValueError):
                artifact.validate_smoke(state, 'owned', 'owned-volume', IMAGE, Path('/fixed/script.sh'))

    def test_dockerfile_preserves_license_source_and_actual_internal_names(self):
        text = artifact.dockerfile()
        for value in (artifact.TOOL_IMAGE, artifact.SOURCE_URL, 'LICENSE NOTICE README.upstream.md',
                      'USER 1000:1000', 'curvine-server', 'curvine-cli', 'CMD ["--help"]'):
            self.assertIn(value, text)
        for forbidden in ('curl', 'wget', 'git clone', 'AWS_ACCESS_KEY', 'ADD https', 'EXPOSE', 'VOLUME'):
            self.assertNotIn(forbidden, text)

    def test_private_json_receipt_mode(self):
        path = self.root / 'receipt.json'
        artifact.write_json(path, {'source': REVISION})
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(json.loads(path.read_text()), {'source': REVISION})

    def test_cleanup_scope_success_and_cache_preservation(self):
        with patch.object(artifact, 'command', return_value=Mock(stdout='unrelated-existing\n')) as command:
            artifact.owned_cleanup(['owned-one', 'owned-two'], 'owned-volume')
        args = [call.args[0] for call in command.call_args_list]
        self.assertEqual(args[:3], [['docker', 'rm', '-f', 'owned-one'], ['docker', 'rm', '-f', 'owned-two'],
                                   ['docker', 'volume', 'rm', 'owned-volume']])
        self.assertFalse(any('prune' in call or 'unrelated-existing' in call for call in args))
        self.assertFalse(any(volume in arg for arg in args for volume in artifact.VOLUMES))

    def test_cleanup_failure_still_attempts_all_and_never_claims_pass(self):
        calls = []
        def run(args):
            calls.append(args)
            if args[:2] == ['docker', 'rm']:
                raise subprocess.TimeoutExpired('docker', 1)
            return Mock(stdout='owned-one\n')
        with patch.object(artifact, 'command', side_effect=run), self.assertRaises(RuntimeError):
            artifact.owned_cleanup(['owned-one', 'owned-two'], 'owned-volume')
        self.assertIn(['docker', 'rm', '-f', 'owned-two'], calls)
        self.assertIn(['docker', 'volume', 'rm', 'owned-volume'], calls)
        self.assertIn(['docker', 'ps', '-a', '--format', '{{.Names}}'], calls)

    def test_failed_cleanup_also_attempts_owned_image_removal(self):
        with patch.object(artifact, 'owned_cleanup', side_effect=RuntimeError('cleanup failed')), \
                patch.object(artifact, 'command', return_value=Mock()) as command:
            with self.assertRaises(RuntimeError):
                artifact.final_cleanup(['owned'], 'owned-volume', 'runix-fs-local:owned')
        command.assert_called_once_with(['docker', 'image', 'rm', 'runix-fs-local:owned'])

    def test_failed_actual_build_adopts_only_own_label_and_cleans_no_caches(self):
        for own in (True, False):
            runtime = self.root / ('job-owned' if own else 'job-foreign')
            runtime.mkdir()
            calls = []
            def run(args):
                calls.append(args)
                if args[:3] == ['docker', 'image', 'inspect']:
                    return Mock(stdout=json.dumps([{'Os': 'linux', 'Architecture': 'amd64'}]))
                if args[:2] == ['docker', 'inspect']:
                    operation = json.loads((runtime / 'operation.json').read_text())
                    label = operation['run_id'] if own else 'unrelated-operation'
                    return Mock(stdout=json.dumps([{'Config': {'Labels': {'io.runix.artifact': label}}}]))
                return Mock(stdout='')
            with patch.object(artifact.tempfile, 'mkdtemp', return_value=str(runtime)), \
                    patch.object(artifact, 'command', side_effect=run), \
                    patch.object(artifact, 'snapshot', return_value=TREE), \
                    patch.object(artifact.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['synthetic-build'])):
                with self.assertRaises(subprocess.CalledProcessError):
                    artifact.main(self.root, REVISION)
            self.assertFalse((runtime / 'artifact.json').exists())
            removals = [args for args in calls if args[:2] == ['docker', 'rm']]
            self.assertEqual(removals, [['docker', 'rm', '-f', artifact.BUILD_NAME]] if own else [])
            self.assertFalse(any(args[:3] == ['docker', 'volume', 'rm'] for args in calls))

    def test_active_cache_or_existing_builder_refused_before_build_or_removal(self):
        for cache in (True, False):
            runtime = self.root / ('active-cache' if cache else 'existing-builder')
            runtime.mkdir()
            calls = []
            def run(args):
                calls.append(args)
                if args[:3] == ['docker', 'image', 'inspect']:
                    return Mock(stdout=json.dumps([{'Os': 'linux', 'Architecture': 'amd64'}]))
                if args[:3] == ['docker', 'ps', '-q'] and cache:
                    return Mock(stdout='existing-cache-user')
                if args[:3] == ['docker', 'ps', '-aq']:
                    return Mock(stdout='existing-builder')
                return Mock(stdout='')
            with patch.object(artifact.tempfile, 'mkdtemp', return_value=str(runtime)), \
                    patch.object(artifact, 'command', side_effect=run), \
                    patch.object(artifact, 'snapshot') as snapshot, \
                    patch.object(artifact.subprocess, 'run') as build:
                with self.assertRaises(RuntimeError):
                    artifact.main(self.root, REVISION)
                build.assert_not_called()
                snapshot.assert_not_called()
            self.assertFalse(any(args[:2] == ['docker', 'rm'] for args in calls))

    def test_lost_image_volume_or_container_creation_response_still_scopes_cleanup(self):
        for phase in ('image', 'volume', 'smoke'):
            runtime = self.root / ('lost-' + phase)
            runtime.mkdir()
            (self.root / 'scripts/runix').mkdir(parents=True, exist_ok=True)
            (self.root / 'scripts/runix/local_engine_smoke.sh').write_text('synthetic-script')
            calls = []
            def operation():
                return json.loads((runtime / 'operation.json').read_text())
            def snapshot(repo, source, ref):
                source.mkdir()
                for name in ('LICENSE', 'NOTICE', 'README.upstream.md'):
                    (source / name).write_text('synthetic-license-fixture')
                return TREE
            def command(args):
                calls.append(args)
                op = operation()
                if args[:3] == ['docker', 'image', 'inspect']:
                    state = self.image()
                    state['Config']['Labels']['io.runix.artifact'] = op['run_id']
                    return Mock(stdout=json.dumps([state]))
                if args[:3] == ['docker', 'volume', 'create'] and phase == 'volume':
                    raise subprocess.CalledProcessError(1, ['synthetic-lost-volume-response'])
                if args[:3] == ['docker', 'volume', 'inspect']:
                    return Mock(stdout=json.dumps([{'Labels': {'io.runix.artifact': op['run_id']}}]))
                if args[:2] == ['docker', 'inspect']:
                    return Mock(stdout=json.dumps([{'Config': {'Labels': {'io.runix.artifact': op['run_id']}}}]))
                if args[:3] == ['docker', 'run', '-d'] and phase == 'smoke':
                    raise subprocess.CalledProcessError(1, ['synthetic-lost-container-response'])
                return Mock(stdout='')
            def process(args, **kwargs):
                if args[:2] == ['docker', 'build']:
                    (runtime / 'image-id').write_text(IMAGE)
                    if phase == 'image':
                        raise subprocess.CalledProcessError(1, ['synthetic-lost-image-response'])
                return Mock(returncode=0)
            with patch.object(artifact.tempfile, 'mkdtemp', return_value=str(runtime)), \
                    patch.object(artifact, 'command', side_effect=command), \
                    patch.object(artifact, 'snapshot', side_effect=snapshot), \
                    patch.object(artifact, 'receipt', return_value={'synthetic': True}), \
                    patch.object(artifact.subprocess, 'run', side_effect=process):
                with self.assertRaises(subprocess.CalledProcessError):
                    artifact.main(self.root, REVISION)
            op = operation()
            self.assertIn(['docker', 'image', 'rm', op['image_tag']], calls)
            self.assertIn(['docker', 'rm', '-f', artifact.BUILD_NAME], calls)
            if phase in ('volume', 'smoke'):
                self.assertIn(['docker', 'volume', 'rm', op['smoke_volume']], calls)
            if phase == 'smoke':
                self.assertIn(['docker', 'rm', '-f', op['smoke_container']], calls)
            self.assertFalse((runtime / 'artifact.json').exists())
            self.assertFalse(any(args[:3] == ['docker', 'volume', 'rm'] and args[-1] in artifact.VOLUMES for args in calls))

    def test_missing_or_unavailable_inventory_never_proves_cleanup(self):
        for output in ('owned\n', 'owned-volume\n'):
            with patch.object(artifact, 'command', return_value=Mock(stdout=output)), self.assertRaises(RuntimeError):
                artifact.owned_cleanup(['owned'], 'owned-volume')
        with patch.object(artifact, 'command', side_effect=OSError('daemon unavailable')), self.assertRaises(RuntimeError):
            artifact.owned_cleanup(['owned'], 'owned-volume')


if __name__ == '__main__':
    unittest.main()
