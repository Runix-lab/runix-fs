"""Verify Docker failure cleanup leaves unrelated local services alone."""
import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from local_s3_smoke import main


class LocalS3SafetyTests(unittest.TestCase):
    def exercise_failure(self, fail_store):
        containers = {'unrelated-existing-service'}
        networks = {'unrelated-existing-network'}
        with tempfile.TemporaryDirectory() as parent:
            sdk = Path(parent) / 'sdk'
            (sdk / 'boto3').mkdir(parents=True)
            runtime = Path(parent) / 'runtime'
            runtime.mkdir()

            def docker(command, **kwargs):
                self.assertEqual(command[0], 'docker')
                self.assertNotIn('-p', command)
                self.assertNotIn('--publish', command)
                if command[1:3] == ['network', 'create']:
                    self.assertIn('--internal', command)
                    networks.add(command[-1])
                elif command[1] == 'run':
                    name = command[command.index('--name') + 1]
                    containers.add(name)
                    if '-d' in command and fail_store:
                        # Docker may create the container before start fails.
                        raise subprocess.CalledProcessError(125, command)
                    if name.endswith('-engine'):
                        return subprocess.CompletedProcess(command, 1)
                    if '--rm' in command:
                        containers.remove(name)
                elif command[1:3] == ['rm', '-fv']:
                    for name in command[3:]:
                        self.assertTrue(name.startswith('runix-s3-smoke-'))
                        containers.discard(name)
                elif command[1:3] == ['network', 'rm']:
                    networks.discard(command[-1])
                return subprocess.CompletedProcess(command, 0)

            with patch('local_s3_smoke.tempfile.mkdtemp', return_value=str(runtime)), \
                    patch('local_s3_smoke.subprocess.run', side_effect=docker), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises((subprocess.CalledProcessError, RuntimeError)):
                    main(str(sdk))
            self.assertFalse((runtime / 'fixture.env').exists())
            self.assertEqual(runtime.stat().st_mode & 0o777, 0o700)
        self.assertEqual(containers, {'unrelated-existing-service'})
        self.assertEqual(networks, {'unrelated-existing-network'})

    def test_store_start_failure_cleans_created_container(self):
        self.exercise_failure(fail_store=True)

    def test_engine_failure_cleans_only_invocation_resources(self):
        self.exercise_failure(fail_store=False)


if __name__ == '__main__':
    unittest.main()
