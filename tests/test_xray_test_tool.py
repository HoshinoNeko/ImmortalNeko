import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from scripts import fetch_test_xray as tool


class XrayTestToolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('xray', b'fixture executable')
            archive.writestr('../unwanted', b'never extracted')
        self.archive = buffer.getvalue()
        self.digest = hashlib.sha256(self.archive).hexdigest()
        self.assets = patch.object(tool, 'ASSETS', {(tool.platform.system(), tool.platform.machine()): ('fixture.zip', self.digest)})
        self.assets.start(); self.addCleanup(self.assets.stop)

    def test_checksum_verified_staging_extracts_only_the_executable(self):
        def download(args, **_kwargs): Path(args[-1]).write_bytes(self.archive)
        with patch.object(tool.subprocess, 'run', side_effect=download) as run:
            binary = tool.stage(self.root)
            self.assertEqual(binary.read_bytes(), b'fixture executable')
            self.assertEqual(binary.stat().st_mode & 0o777, 0o755)
            self.assertFalse((self.root/'.work/tools/unwanted').exists())
            tool.stage(self.root)
            self.assertEqual(run.call_count, 1)

    def test_download_with_wrong_checksum_never_publishes_a_binary(self):
        def download(args, **_kwargs): Path(args[-1]).write_bytes(b'wrong archive')
        with patch.object(tool.subprocess, 'run', side_effect=download):
            with self.assertRaisesRegex(ValueError, 'checksum'): tool.stage(self.root)
        self.assertFalse((self.root/'.work/tools'/('xray-'+tool.VERSION)/'xray').exists())
