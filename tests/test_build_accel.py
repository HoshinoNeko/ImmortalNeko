import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import build_accel as accel
from scripts.fwlib import BuildError, profile


class BuildAccelerationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)

    def test_profiles_share_only_their_compatible_compiler_cache_scope(self):
        basic = accel.cache_plan(profile('x86-basic'), 'Linux', 'X64')
        ha = accel.cache_plan(profile('x86-ha'), 'Linux', 'X64')
        arm = accel.cache_plan(profile('r619ac-basic'), 'Linux', 'X64')
        self.assertEqual(basic['downloads_prefix'], ha['downloads_prefix'])
        self.assertEqual(basic['compiler_prefix'], ha['compiler_prefix'])
        self.assertNotEqual(basic['go_prefix'], ha['go_prefix'])
        self.assertEqual(basic['downloads_prefix'], arm['downloads_prefix'])
        self.assertNotEqual(basic['compiler_prefix'], arm['compiler_prefix'])
        self.assertNotEqual(basic['go_prefix'], arm['go_prefix'])
        self.assertNotEqual(basic['compiler_prefix'], accel.cache_plan(profile('x86-basic'), 'Linux', 'ARM64')['compiler_prefix'])

    def test_source_and_feed_updates_change_compiler_scope_but_downloads_have_a_fallback(self):
        with patch.object(accel, 'locked_repos', return_value=({'commit': 'a'*40}, [{'commit': 'b'*40}])):
            before = accel.cache_plan(profile('x86-basic'), 'Linux', 'X64')
        with patch.object(accel, 'locked_repos', return_value=({'commit': 'a'*40}, [{'commit': 'c'*40}])):
            after = accel.cache_plan(profile('x86-basic'), 'Linux', 'X64')
        self.assertNotEqual(before['compiler_prefix'], after['compiler_prefix'])
        self.assertEqual(before['downloads_fallback'], after['downloads_fallback'])

    def test_cache_platform_cannot_inject_an_action_output(self):
        with self.assertRaises(BuildError): accel.cache_plan(profile('x86-basic'), 'Linux\nvalue=bad', 'X64')

    def test_ui_changes_keep_caches_but_native_dependencies_change_go_scope(self):
        package = self.base/'local-packages/demo'; package.mkdir(parents=True)
        (package/'Makefile').write_text('demo package')
        javascript = package/'view.js'; javascript.write_text('old UI')
        header = package/'api.h'; header.write_text('old native header')
        selected = profile('x86-ha')
        with patch.object(accel, 'ROOT', self.base):
            first = accel.cache_plan(selected, 'Linux', 'X64')
            javascript.write_text('new UI')
            self.assertEqual(first, accel.cache_plan(selected, 'Linux', 'X64'))
            header.write_text('new native header')
            updated = accel.cache_plan(selected, 'Linux', 'X64')
        self.assertEqual(first['compiler_prefix'], updated['compiler_prefix'])
        self.assertNotEqual(first['go_prefix'], updated['go_prefix'])

    def test_auto_parallelism_respects_cpus_memory_and_upper_bound(self):
        self.assertEqual(accel.select_jobs(cpus=4, memory=14*accel.GIB), 4)
        self.assertEqual(accel.select_jobs(cpus=2, memory=14*accel.GIB), 2)
        self.assertEqual(accel.select_jobs(cpus=8, memory=6*accel.GIB), 2)
        self.assertEqual(accel.select_jobs(cpus=64, memory=128*accel.GIB), 8)
        self.assertEqual(accel.select_jobs(cpus=4, memory=accel.GIB), 1)
        self.assertEqual(accel.select_jobs('4', cpus=2, memory=accel.GIB), 4)
        for value in ('0', '17', 'many'):
            with self.assertRaises(BuildError): accel.select_jobs(value)

    def test_go_cache_survives_a_fresh_source_tree(self):
        work = self.base/'work'; work.mkdir()
        first = work/'source'; first.mkdir()
        accel.bind_go_cache(first, work)
        (first/'tmp/go-build/result').write_text('cached object')
        accel.bind_go_cache(first, work)
        first.rename(work/'previous-source')
        second = work/'source'; second.mkdir()
        accel.bind_go_cache(second, work)
        self.assertEqual((second/'tmp/go-build/result').read_text(), 'cached object')
        self.assertEqual((second/'tmp/go-build').resolve(), (work/'go-build').resolve())

    def test_existing_go_path_is_never_overwritten(self):
        source = self.base/'source'; (source/'tmp/go-build').mkdir(parents=True)
        sentinel = source/'tmp/go-build/entry'; sentinel.write_text('keep')
        with self.assertRaises(BuildError): accel.bind_go_cache(source, self.base)
        self.assertEqual(sentinel.read_text(), 'keep')

    def test_external_cache_symlink_is_rejected(self):
        target = self.base/'outside'; target.mkdir()
        work = self.base/'work'; work.mkdir(); (work/'go-build').symlink_to(target)
        with self.assertRaises(BuildError): accel.bind_go_cache(work/'source', work)
        with self.assertRaises(BuildError): accel.prune_go_cache(work/'go-build')

    def test_failed_build_still_records_timing_and_keeps_its_exit_code(self):
        with self.assertRaises(subprocess.CalledProcessError) as error:
            accel.timed_run(self.base, 'compile', [sys.executable, '-c', 'raise SystemExit(7)'], self.base)
        self.assertEqual(error.exception.returncode, 7)
        record = json.loads((self.base/'logs/compile-timing.json').read_text())
        self.assertEqual(record['exit_code'], 7)
        self.assertGreaterEqual(record['seconds'], 0)

    def test_timing_write_failure_cannot_replace_the_compiler_error(self):
        (self.base/'logs').write_text('not a directory')
        with self.assertRaises(subprocess.CalledProcessError) as error:
            accel.timed_run(self.base, 'compile', [sys.executable, '-c', 'raise SystemExit(8)'], self.base)
        self.assertEqual(error.exception.returncode, 8)

    def test_go_cache_trim_removes_oldest_entries_and_never_follows_symlinks(self):
        cache = self.base/'go-build'; cache.mkdir()
        old = cache/'old'; old.write_bytes(b'a'*8); os.utime(old, (10, 10))
        new = cache/'new'; new.write_bytes(b'b'*8); os.utime(new, (20, 20))
        outside = self.base/'outside'; outside.mkdir(); (outside/'entry').write_bytes(b'c'*100)
        (cache/'link').symlink_to(outside)
        self.assertEqual(accel.prune_go_cache(cache, 10), 8)
        self.assertFalse(old.exists()); self.assertTrue(new.exists())
        self.assertEqual((outside/'entry').stat().st_size, 100)

    def test_report_describes_restored_prefix_matches_and_failed_builds(self):
        logs = self.base/'logs'; logs.mkdir()
        (logs/'acceleration-plan.json').write_text(json.dumps({'jobs': 4}))
        (logs/'compile-timing.json').write_text(json.dumps({'phase': 'compile', 'seconds': 120, 'exit_code': 2}))
        summary = self.base/'summary.md'
        with patch.dict(os.environ, {'GITHUB_STEP_SUMMARY': str(summary), 'COMPILER_MATCHED': 'prefix-old-run', 'DOWNLOADS_MATCHED': '', 'GO_MATCHED': ''}):
            accel.report(self.base)
        result = json.loads((logs/'build-metrics.json').read_text())
        self.assertTrue(result['restored']['compiler'])
        self.assertFalse(result['restored']['downloads'])
        self.assertEqual(result['phases'][0]['exit_code'], 2)
        self.assertIn('2.0 min; exit 2', summary.read_text())


if __name__ == '__main__': unittest.main()
