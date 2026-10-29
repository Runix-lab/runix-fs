"""Orchestrator fault tests; real engine evidence is a separate integration run."""
import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_tenant_smoke import main


class TenantSmokeSafetyTests(unittest.TestCase):
    def failure(self, stage):
        containers, networks = {'unrelated-service'}, {'unrelated-network'}
        with tempfile.TemporaryDirectory() as directory:
            sdk = Path(directory) / 'sdk'
            (sdk / 'boto3').mkdir(parents=True)
            runtime = Path(directory) / 'runtime'
            runtime.mkdir()
            def docker(command, **kwargs):
                self.assertEqual(command[0], 'docker')
                self.assertGreater(kwargs['timeout'], 0)
                self.assertNotIn('-p', command)
                self.assertNotIn('--publish', command)
                self.assertNotIn('--privileged', command)
                output = ''
                if command[1:3] == ['network', 'create']:
                    self.assertIn('--internal', command)
                    networks.add(command[-1])
                elif command[1] == 'inspect':
                    network = command[2].removesuffix('-store')
                    output = json.dumps([{'HostConfig': {'PortBindings': {}},
                                          'NetworkSettings': {'Networks': {network: {'IPAddress': '172.30.0.2'}}}}])
                elif command[1:3] == ['network', 'inspect']:
                    output = json.dumps([{'Internal': True}])
                elif command[1] == 'run':
                    name = command[command.index('--name') + 1]
                    envfile = Path(command[command.index('--env-file') + 1])
                    self.assertEqual(envfile.stat().st_mode & 0o777, 0o600)
                    env = envfile.read_text()
                    if name.endswith('-engine') or '-d' in command:
                        self.assertNotIn('RUNIX_PEER_SECRET', env)
                    if command[-1].endswith('local_tenant_probe.py'):
                        self.assertIn('RUNIX_PEER_SECRET', env)
                    containers.add(name)
                    if '-d' in command and stage == 'store':
                        raise subprocess.CalledProcessError(125, command)
                    if name.endswith('-client') and command[-1].endswith('local_tenant_probe.py') and stage == 'probe':
                        raise subprocess.TimeoutExpired(command, 90)
                    if name.endswith('-engine'):
                        raise subprocess.CalledProcessError(1, command)
                    if '--rm' in command:
                        containers.remove(name)
                elif command[1:3] == ['rm', '-fv']:
                    for name in command[3:]:
                        self.assertTrue(name.startswith('runix-tenant-smoke-'))
                        if stage != 'cleanup' or not name.endswith('-store'):
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
            with patch('local_tenant_smoke.tempfile.mkdtemp', return_value=str(runtime)), \
                    patch('local_tenant_smoke.subprocess.run', side_effect=docker), \
                    contextlib.redirect_stdout(io.StringIO()) as printed:
                with self.assertRaises((subprocess.SubprocessError, RuntimeError)) as caught:
                    main(str(sdk))
                self.assertNotIn('all owned containers/networks removed', printed.getvalue())
                if stage == 'cleanup':
                    self.assertIsInstance(caught.exception, RuntimeError)
                    self.assertIn('could not be confirmed removed', str(caught.exception))
            self.assertFalse(any(runtime.rglob('*.env')))
            self.assertFalse((runtime / 'evidence.json').exists())
            self.assertEqual(runtime.stat().st_mode & 0o777, 0o700)
        self.assertIn('unrelated-service', containers)
        self.assertEqual(networks, {'unrelated-network'})
        if stage != 'cleanup':
            self.assertEqual(containers, {'unrelated-service'})

    def test_partial_store_start_failure(self):
        self.failure('store')

    def test_probe_timeout(self):
        self.failure('probe')

    def test_actual_engine_failure(self):
        self.failure('engine')

    def test_cleanup_failure_is_not_silently_successful(self):
        self.failure('cleanup')

    def test_daemon_inventory_failure_is_not_cleanup_proof(self):
        self.failure('inventory')


if __name__ == '__main__':
    unittest.main()
