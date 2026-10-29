"""Ensure negative probes require positive controls and real authorization denial."""
import contextlib
import io
import unittest
from unittest.mock import Mock, patch

from botocore.exceptions import ClientError

from local_tenant_probe import main


class TenantProbeTests(unittest.TestCase):
    def setUp(self):
        self.own, self.foreign = Mock(), Mock()
        self.own.get_object.return_value = {'Body': io.BytesIO(b'x' * (4 * 1024 * 1024))}
        self.foreign.get_object.side_effect = ClientError(
            {'ResponseMetadata': {'HTTPStatusCode': 403},
             'Error': {'Code': 'InvalidAccessKeyId'}}, 'GetObject')
        self.env = patch.dict('os.environ', {'AWS_ACCESS_KEY_ID': 'own-test',
            'AWS_SECRET_ACCESS_KEY': 'own-secret-test', 'RUNIX_PEER_IP': '192.0.2.1',
            'RUNIX_PEER_ACCESS': 'peer-test', 'RUNIX_PEER_SECRET': 'peer-secret-test'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.factory = patch('local_tenant_probe.boto3.client', side_effect=[self.own, self.foreign]).start()
        self.addCleanup(patch.stopall)
        self.network = patch('local_tenant_probe.socket.create_connection', side_effect=TimeoutError).start()

    def test_success_requires_own_data_and_two_separate_negative_checks(self):
        with contextlib.redirect_stdout(io.StringIO()):
            main()
        self.network.assert_called_once_with(('192.0.2.1', 9000), timeout=3)
        for call in self.factory.call_args_list:
            self.assertEqual(call.kwargs['endpoint_url'], 'http://objectstore:9000')
            self.assertTrue(call.kwargs['config'].ignore_configured_endpoint_urls)
        self.assertEqual(self.factory.call_args_list[1].kwargs['aws_access_key_id'], 'peer-test')
        self.foreign.get_object.assert_called_once()

    def test_wrong_positive_payload_cannot_count_as_isolation(self):
        self.own.get_object.return_value = {'Body': io.BytesIO(b'')}
        with self.assertRaises(RuntimeError):
            main()
        self.network.assert_not_called()

    def test_reachable_peer_fails_and_closes_socket(self):
        self.network.side_effect = None
        with self.assertRaises(RuntimeError):
            main()
        self.network.return_value.close.assert_called_once()
        self.foreign.get_object.assert_not_called()

    def test_foreign_credential_success_fails(self):
        self.foreign.get_object.side_effect = None
        with self.assertRaises(RuntimeError):
            main()

    def test_throttle_or_internal_error_is_not_authorization_denial(self):
        for code, status in (('InternalError', 500), ('SlowDown', 503), ('NoSuchKey', 404)):
            self.factory.side_effect = [self.own, self.foreign]
            self.own.get_object.return_value = {'Body': io.BytesIO(b'x' * (4 * 1024 * 1024))}
            self.foreign.get_object.side_effect = ClientError(
                {'ResponseMetadata': {'HTTPStatusCode': status}, 'Error': {'Code': code}}, 'GetObject')
            with self.subTest(code=code), self.assertRaises(RuntimeError):
                main()


if __name__ == '__main__':
    unittest.main()
