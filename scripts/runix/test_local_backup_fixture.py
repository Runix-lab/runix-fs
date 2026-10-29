"""Integrity and bounded synthetic export/import tests, without any cloud request."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from local_backup_fixture import BUCKET, KEYS, SIZE, export_objects, import_objects


class BackupFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payloads = dict(zip(KEYS, (b'a' * SIZE, b'b' * SIZE)))
        self.client = Mock()
        self.client.list_objects_v2.return_value = {
            'IsTruncated': False, 'Contents': [{'Key': key} for key in reversed(KEYS)]}
        self.client.get_object.side_effect = lambda **args: {'Body': io.BytesIO(self.payloads[args['Key']])}

    def test_complete_export_and_import(self):
        manifest = export_objects(self.client, self.root)
        self.client.list_objects_v2.assert_called_once_with(Bucket=BUCKET, MaxKeys=3)
        destination = Mock()
        destination.get_object.side_effect = lambda **args: {'Body': io.BytesIO(self.payloads[args['Key']])}
        self.assertEqual(import_objects(destination, self.root), manifest)
        destination.create_bucket.assert_called_once_with(Bucket=BUCKET)
        self.assertEqual(destination.put_object.call_count, 2)
        self.assertEqual(destination.get_object.call_count, 2)
        for call in destination.put_object.call_args_list:
            self.assertEqual(call.kwargs['Body'], self.payloads[call.kwargs['Key']])
        self.assertEqual((self.root / 'backup').stat().st_mode & 0o777, 0o700)

    def test_truncated_missing_duplicate_or_foreign_listing_denied_before_reads(self):
        for listing in ({'IsTruncated': True, 'Contents': [{'Key': key} for key in KEYS]},
                        {'IsTruncated': False, 'Contents': [{'Key': KEYS[0]}]},
                        {'IsTruncated': False, 'Contents': [{'Key': KEYS[0]}] * 2},
                        {'IsTruncated': False, 'Contents': [{'Key': '../escape'}, {'Key': KEYS[1]}]},
                        {}):
            self.client.list_objects_v2.return_value = listing
            with self.assertRaises(ValueError):
                export_objects(self.client, self.root)
        self.client.get_object.assert_not_called()
        self.assertFalse((self.root / 'backup').exists())

    def test_partial_source_export_never_writes_a_manifest(self):
        self.payloads[KEYS[1]] = b'bad'
        with self.assertRaises(ValueError):
            export_objects(self.client, self.root)
        self.assertFalse((self.root / 'backup/manifest.json').exists())

    def test_corrupt_second_payload_causes_zero_destination_mutations(self):
        export_objects(self.client, self.root)
        (self.root / 'backup/upload.bin').write_bytes(b'c' * SIZE)
        destination = Mock()
        with self.assertRaises(ValueError):
            import_objects(destination, self.root)
        self.assertEqual(destination.mock_calls, [])

    def test_missing_payload_causes_zero_destination_mutations(self):
        export_objects(self.client, self.root)
        (self.root / 'backup/source.bin').unlink()
        destination = Mock()
        with self.assertRaises(FileNotFoundError):
            import_objects(destination, self.root)
        self.assertEqual(destination.mock_calls, [])

    def test_manifest_substitution_and_path_injection_denied(self):
        good = export_objects(self.client, self.root)
        variants = [[], {**good, 'version': True}, {**good, 'unknown': 1},
                    {**good, 'objects': {'../escape': good['objects'][KEYS[0]], KEYS[1]: good['objects'][KEYS[1]]}},
                    {**good, 'objects': {**good['objects'], KEYS[0]: {'bytes': SIZE, 'sha256': 'bad'}}},
                    {**good, 'objects': {**good['objects'], KEYS[1]: {'bytes': SIZE + 1, 'sha256': 'bad'}}}]
        for manifest in variants:
            (self.root / 'backup/manifest.json').write_text(json.dumps(manifest))
            destination = Mock()
            with self.subTest(manifest_type=type(manifest).__name__), self.assertRaises(ValueError):
                import_objects(destination, self.root)
            self.assertEqual(destination.mock_calls, [])

    def test_oversized_manifest_denied(self):
        export_objects(self.client, self.root)
        (self.root / 'backup/manifest.json').write_bytes(b' ' * 4097)
        destination = Mock()
        with self.assertRaises(ValueError):
            import_objects(destination, self.root)
        self.assertEqual(destination.mock_calls, [])

    def test_destination_write_failure_is_not_reported_as_success(self):
        export_objects(self.client, self.root)
        destination = Mock()
        destination.put_object.side_effect = [None, RuntimeError('synthetic failure')]
        with self.assertRaises(RuntimeError):
            import_objects(destination, self.root)
        self.assertEqual(destination.put_object.call_count, 2)

    def test_destination_ack_without_correct_bytes_is_not_restore_success(self):
        export_objects(self.client, self.root)
        destination = Mock()
        destination.get_object.return_value = {'Body': io.BytesIO(b'corrupt')}
        with self.assertRaises(ValueError):
            import_objects(destination, self.root)


if __name__ == '__main__':
    unittest.main()
