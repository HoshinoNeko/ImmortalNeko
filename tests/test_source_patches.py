import difflib
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.fwlib import BuildError
from scripts.sources import apply_patches


class SourcePatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.src=self.root/'source';self.src.mkdir()
        self.patches=self.root/'patches';self.patches.mkdir()

    def add_patch(self, directory, name, before, after):
        directory.mkdir(parents=True,exist_ok=True)
        (directory/'change.patch').write_text(''.join(difflib.unified_diff(
            before.splitlines(keepends=True),after.splitlines(keepends=True),fromfile='a/'+name,tofile='b/'+name)))
        (directory/'series').write_text('change.patch\n')

    def apply(self):
        with patch('scripts.sources.ROOT',self.root),patch('scripts.sources.locked_repos',return_value=({},[{'name':'luci'}])):
            apply_patches(self.src,{'name':'x86-ha'})

    def test_main_and_feed_patch_series_apply_in_their_own_trees(self):
        feed=self.src/'feeds/luci';feed.mkdir(parents=True)
        (self.src/'main.txt').write_text('original\n');(feed/'app.txt').write_text('old\n')
        self.add_patch(self.patches/'common','main.txt','original\n','patched\n')
        self.add_patch(self.patches/'feeds/luci','app.txt','old\n','new\n')
        self.apply()
        self.assertEqual((self.src/'main.txt').read_text(),'patched\n')
        self.assertEqual((feed/'app.txt').read_text(),'new\n')
        self.assertFalse((self.src/'app.txt').exists())

    def test_missing_feed_patch_target_is_fatal(self):
        self.add_patch(self.patches/'feeds/luci','app.txt','old\n','new\n')
        with self.assertRaisesRegex(BuildError,'Missing pinned feed'):self.apply()

    def test_failed_patch_does_not_mutate_the_target(self):
        (self.src/'main.txt').write_text('changed upstream\n')
        self.add_patch(self.patches/'common','main.txt','original\n','patched\n')
        with self.assertRaises(subprocess.CalledProcessError):self.apply()
        self.assertEqual((self.src/'main.txt').read_text(),'changed upstream\n')
