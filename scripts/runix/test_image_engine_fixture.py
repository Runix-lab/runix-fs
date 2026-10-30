"""Pinned-image fixture boundaries and failure recovery; no real Docker calls."""
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import engine_artifact as a
from image_engine_fixture import ImageEngineFixture

IMAGE, REVISION = 'sha256:' + 'a' * 64, 'b' * 40


class ImageFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder = self.root / 'runtime'
        self.folder.mkdir(mode=0o700)
        for name in ('source.bin', 'upload.bin'):
            (self.folder / name).write_bytes(b'synthetic')
        self.script = self.root / 'local_s3_engine_smoke.sh'
        self.script.write_text('#!/bin/bash\nexit 0\n')
        self.receipt = self.root / 'artifact.json'
        self.build = dict(schema=1, image_id=IMAGE, source_commit=REVISION, production_release=False,
            smoke=dict(actual_write_read_restart=True, owned_resources_removed=True))
        self.receipt.write_text(json.dumps(self.build))
        self.image = dict(Id=IMAGE, Os='linux', Architecture='amd64', Config=dict(User='1000:1000',
            Entrypoint=['/opt/runix/bin/curvine-server'], Cmd=['--help'], Volumes=None, ExposedPorts=None,
            Labels={'org.opencontainers.image.revision': REVISION, 'org.opencontainers.image.source': a.SOURCE_URL}))
        self.runner = ImageEngineFixture.__new__(ImageEngineFixture)
        self.runner.build, self.runner.image = self.build, IMAGE

    def test_receipt_and_actual_image_are_checked_before_resource_creation(self):
        for change in ({'production_release': True}, {'schema': 2}, {'source_commit': 'main'},
                       {'smoke': {'actual_write_read_restart': False}}, {}):
            self.receipt.write_text(json.dumps(dict(self.build, **change)))
            state = copy.deepcopy(self.image)
            if not change:
                state['Config']['User'] = '0'
            with patch.object(a, 'command', return_value=Mock(stdout=json.dumps([state]))) as docker:
                with self.assertRaises(ValueError):
                    ImageEngineFixture(self.receipt)
                self.assertTrue(all(call.args[0][1:3] == ['image', 'inspect'] for call in docker.call_args_list))
        self.receipt.write_bytes(b'x' * 65537)
        with patch.object(a, 'command') as docker, self.assertRaises(ValueError):
            ImageEngineFixture(self.receipt)
        docker.assert_not_called()

    def test_noninternal_network_and_invalid_or_reused_inputs_are_refused(self):
        with patch.object(a, 'command', return_value=Mock(stdout=json.dumps([dict(Name='test-net', Internal=False)]))) as docker:
            with self.assertRaises(ValueError):
                self.runner.run(self.folder, 'test-net', 'owned', self.root / 'fixture.env', self.script)
            self.assertEqual(docker.call_count, 1)
        (self.folder / 'image-execution.json').write_text('{}')
        with patch.object(a, 'command') as docker, self.assertRaises(ValueError):
            self.runner.run(self.folder, 'test-net', 'owned', self.root / 'fixture.env', self.script)
        docker.assert_not_called()
        (self.folder / 'image-execution.json').unlink()
        (self.folder / 'source.bin').unlink()
        (self.folder / 'source.bin').symlink_to(self.folder / 'upload.bin')
        with self.assertRaises(ValueError):
            self.runner._inputs(self.folder, False)

    def test_restore_requires_complete_regular_stopped_state(self):
        (self.folder / 'cluster.toml').write_text('format_master=false')
        (self.folder / 'data').mkdir()
        with self.assertRaises(ValueError):
            self.runner._inputs(self.folder, True)
        for name in ('meta', 'journal', 'worker'):
            (self.folder / 'data' / name).mkdir()
        self.assertEqual(self.runner._inputs(self.folder, True), ['source.bin', 'upload.bin', 'cluster.toml', 'data'])
        (self.folder / 'data/meta/bad-link').symlink_to(self.root)
        with self.assertRaises(ValueError):
            self.runner._inputs(self.folder, True)

    def exercise(self, failure=None):
        containers, volumes = {'unrelated-service': {}}, {'unrelated-volume'}
        commands, started = [], []
        def docker(args, **kwargs):
            commands.append(args)
            output = ''
            if args[1:3] == ['network', 'inspect']:
                output = json.dumps([dict(Name='test-net', Internal=True)])
            elif args[1:3] == ['volume', 'create']:
                volumes.add(args[-1])
                if failure == 'volume':
                    raise subprocess.CalledProcessError(125, args)
            elif args[1:3] == ['volume', 'inspect']:
                output = json.dumps([dict(Labels={'io.runix.artifact': next(c[c.index('--label')+1].split('=',1)[1] for c in commands if c[1:3]==['volume','create'])})])
            elif args[1] in ('run', 'create'):
                name = args[args.index('--name') + 1]
                label = args[args.index('--label') + 1].split('=', 1)[1]
                prep = name.endswith('-prepare')
                state = dict(Name='/' + name, Image=IMAGE, State=dict(Running=prep, ExitCode=0),
                    Config=dict(User='0:0' if prep else '1000:1000', Labels={'io.runix.artifact': label},
                        Env=['RUNIX_EXPECTED_SMOKE_SHA256=' + a.file_digest(self.script)['sha256']]),
                    HostConfig=dict(NetworkMode='none' if prep else 'test-net', ReadonlyRootfs=True,
                        CapDrop=['ALL'], SecurityOpt=['no-new-privileges'], Privileged=False, PortBindings={}),
                    NetworkSettings={'Networks': {'test-net': {}}},
                    Mounts=[dict(Destination='/smoke', Type='volume', Name='owned-data', RW=True),
                            dict(Destination='/run-smoke.sh', Type='bind', Source=str(self.script.resolve()), RW=False)])
                containers[name] = state
                if prep:
                    self.assertNotIn('--env-file', args)
                    self.assertEqual(args[-1], 'exec sleep 600')
                else:
                    self.assertNotIn('target=/build', ' '.join(args))
                    self.assertNotIn('-p', args)
                    if failure == 'unsafe':
                        state['Config']['User'] = '0:0'
                    elif failure == 'capability':
                        state['HostConfig']['CapAdd'] = ['SYS_ADMIN']
                if failure == ('prepare' if prep else 'create'):
                    raise subprocess.CalledProcessError(125, args)
            elif args[1] == 'inspect':
                output = json.dumps([containers[args[-1]]])
            elif args[1] == 'exec' and failure == 'chown':
                raise subprocess.CalledProcessError(1, args)
            elif args[1] == 'kill':
                containers[args[-1]]['State']['Running'] = False
            elif args[1] == 'cp' and ':/smoke/.' in args[2]:
                name = args[2].split(':', 1)[0]
                self.assertFalse(containers[name]['State']['Running'], 'never copy an open DB')
            elif args[1:3] == ['rm', '-f']:
                containers.pop(args[-1], None)
            elif args[1:3] == ['volume', 'rm']:
                if failure != 'cleanup':
                    volumes.discard(args[-1])
            elif args[1] == 'ps':
                output = '\n'.join(containers)
            elif args[1:3] == ['volume', 'ls']:
                output = '\n'.join(volumes)
            return Mock(stdout=output)
        def start(args, **kwargs):
            self.assertEqual(args[:3], ['docker', 'start', '-a'])
            name = args[-1]
            started.append(name)
            if failure == 'timeout':
                containers[name]['State']['Running'] = True
                raise subprocess.TimeoutExpired(args, 480)
            if failure == 'start':
                containers[name]['State']['ExitCode'] = 1
                raise subprocess.CalledProcessError(1, args)
            return Mock(returncode=0)
        error = RuntimeError('identity mismatch') if failure == 'identity' else None
        with patch.object(a, 'command', side_effect=docker), \
                patch('image_engine_fixture.subprocess.run', side_effect=start), \
                patch.object(a, 'validate_execution', side_effect=error) as identity:
            if failure:
                with self.assertRaises((RuntimeError, ValueError, subprocess.SubprocessError)):
                    self.runner.run(self.folder, 'test-net', 'owned', self.root / 'fixture.env', self.script)
                self.assertFalse((self.folder / 'image-execution.json').exists())
            else:
                result = self.runner.run(self.folder, 'test-net', 'owned', self.root / 'fixture.env', self.script)
                self.assertEqual(result['runtime_uid'], 1000)
                self.assertTrue(result['stopped_before_copy'])
                self.assertTrue(result['owned_resources_removed'])
                identity.assert_called_once()
        self.assertEqual(containers, {'unrelated-service': {}})
        self.assertEqual(volumes, {'unrelated-volume', 'owned-data'} if failure == 'cleanup' else {'unrelated-volume'})
        if failure in ('volume', 'prepare', 'chown', 'create', 'unsafe', 'capability'):
            self.assertEqual(started, [])

    def test_success_uses_verified_nonroot_image_and_stopped_copy(self):
        self.exercise()

    def test_creation_failures_adopt_owned_resources_and_preserve_unrelated(self):
        for stage in ('volume', 'prepare', 'chown', 'create'):
            with self.subTest(stage=stage):
                self.exercise(stage)

    def test_unsafe_runtime_is_rejected_before_start(self):
        for stage in ('unsafe', 'capability'):
            with self.subTest(stage=stage):
                self.exercise(stage)

    def test_runtime_failure_timeout_and_identity_mismatch_never_issue_receipt(self):
        for stage in ('start', 'timeout', 'identity'):
            with self.subTest(stage=stage):
                self.exercise(stage)

    def test_cleanup_failure_prevents_passing_receipt(self):
        self.exercise('cleanup')

    def test_shell_entry_points_reject_bad_binary_directories_before_io(self):
        for script in ('local_s3_engine_smoke.sh', 'local_restore_engine_smoke.sh'):
            for value in ('relative/path', str(self.root)):
                result = subprocess.run(['bash', str(Path(__file__).with_name(script))],
                    env={'RUNIX_ENGINE_BIN_DIR': value}, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn('absolute existing engine binary directory', result.stderr)
