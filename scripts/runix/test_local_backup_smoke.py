"""Fault injection for backup orchestration; not a simulated successful service."""
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_backup_smoke import main


class BackupRunnerSafetyTests(unittest.TestCase):
    def failure(self, stage):
        containers, networks = {'unrelated-service'}, {'unrelated-network'}
        restore_started = False
        with tempfile.TemporaryDirectory() as directory:
            sdk = Path(directory) / 'sdk'
            (sdk / 'boto3').mkdir(parents=True)
            runtime = Path(directory) / 'runtime'
            runtime.mkdir()
            def docker(command, **kwargs):
                nonlocal restore_started
                self.assertEqual(command[0], 'docker')
                self.assertGreater(kwargs['timeout'], 0)
                self.assertNotIn('-p', command)
                self.assertNotIn('--privileged', command)
                output = ''
                if command[1:3] == ['network', 'create']:
                    self.assertIn('--internal', command)
                    if command[-1].endswith('-restore'):
                        restore_started = True
                        self.assertFalse(any('-original' in name for name in containers | networks))
                    networks.add(command[-1])
                elif command[1] == 'inspect':
                    network = command[-1].removesuffix('-store')
                    output = json.dumps([{'HostConfig': {'PortBindings': {}},
                                          'NetworkSettings': {'Networks': {network: {}}}}])
                elif command[1:3] == ['network', 'inspect']:
                    output = '[{"Internal": true}]'
                elif command[1] == 'run':
                    name = command[command.index('--name') + 1]
                    containers.add(name)
                    if stage == 'start' and '-d' in command:
                        raise subprocess.CalledProcessError(125, command)
                    if name.endswith('-engine'):
                        if stage == 'engine' or (stage == 'restore' and '-restore-engine' in name):
                            raise subprocess.CalledProcessError(1, command)
                        original = runtime / 'original'
                        if '-original-engine' in name:
                            for folder in ('data/meta', 'data/journal', 'data/worker'):
                                (original / folder).mkdir(parents=True, exist_ok=True)
                            for file in ('cluster.toml', 'source.bin', 'upload.bin'):
                                (original / file).write_text('synthetic test marker')
                            if stage == 'live':
                                return subprocess.CompletedProcess(command, 0)
                        if '-restore-engine' in name:
                            self.assertNotIn(f'type=bind,source={original},target=/smoke', command)
                    if command[-1] == 'export':
                        backup = runtime / 'original/backup'
                        backup.mkdir()
                        (backup / 'manifest.json').write_text('{"version": 1, "objects": {}}')
                    if '--rm' in command:
                        containers.remove(name)
                elif command[1:3] == ['rm', '-fv']:
                    for name in command[3:]:
                        self.assertTrue(name.startswith('runix-backup-smoke-'))
                        if stage != 'remove' or not name.endswith('-original-store'):
                            containers.discard(name)
                elif command[1:3] == ['network', 'rm']:
                    networks.discard(command[-1])
                elif command[1] == 'ps':
                    if stage == 'inventory':
                        raise subprocess.CalledProcessError(1, command)
                    output = '\n'.join(containers)
                elif command[1:3] == ['network', 'ls']:
                    output = '\n'.join(networks)
                return subprocess.CompletedProcess(command, 0, stdout=output)
            with patch('local_backup_smoke.tempfile.mkdtemp', return_value=str(runtime)), \
                    patch('local_backup_smoke.subprocess.run', side_effect=docker), \
                    contextlib.redirect_stdout(io.StringIO()) as printed:
                with self.assertRaises((RuntimeError, subprocess.SubprocessError)):
                    main(str(sdk))
                self.assertNotIn('backup/restore test resources removed', printed.getvalue())
            self.assertFalse((runtime / 'fixture.env').exists())
            self.assertFalse((runtime / 'evidence.json').exists())
            if stage != 'restore':
                self.assertFalse(restore_started)
        self.assertIn('unrelated-service', containers)
        self.assertEqual(networks, {'unrelated-network'})
        if stage != 'remove':
            self.assertEqual(containers, {'unrelated-service'})

    def test_partial_store_start_cleanup(self):
        self.failure('start')

    def test_source_engine_failure_cleanup(self):
        self.failure('engine')

    def test_live_source_refuses_db_copy(self):
        self.failure('live')

    def test_original_cleanup_failure_prevents_restore(self):
        self.failure('remove')

    def test_restore_engine_failure_cleans_fresh_boundary(self):
        self.failure('restore')

    def test_inventory_failure_is_not_cleanup_evidence(self):
        self.failure('inventory')


if __name__ == '__main__':
    unittest.main()
