import json
from pathlib import Path
import tempfile
import unittest
from scripts.fwlib import BuildError, ROOT, assert_config, config_values, locked_repos, profile, requested_config, safe_path, scan_tree
from scripts.import_legacy import installed_names, propose, config_schema

class BuilderTests(unittest.TestCase):
    def test_source_and_all_feeds_are_pinned(self):
        s,feeds=locked_repos()
        self.assertEqual(s['release'],'v25.12.2')
        self.assertEqual(len(feeds),5)
    def test_profiles_request_all_four_x86_outputs(self):
        for name in ('x86-basic','x86-ha'):
            p=profile(name); c=requested_config(p)
            for k in ('CONFIG_GRUB_IMAGES','CONFIG_GRUB_EFI_IMAGES','CONFIG_TARGET_ROOTFS_EXT4FS','CONFIG_TARGET_ROOTFS_SQUASHFS'):
                self.assertEqual(c[k],'y')
            self.assertEqual(len(p['required_artifacts']),5)
    def test_basic_excludes_optional_services(self):
        c=requested_config(profile('x86-basic'))
        self.assertNotIn('CONFIG_PACKAGE_firmware-ha',c)
        self.assertNotIn('CONFIG_PACKAGE_ddns-go',c)
    def test_missing_package_is_fatal(self):
        with self.assertRaisesRegex(BuildError,'unavailable_pkg'):
            assert_config({'CONFIG_PACKAGE_unavailable_pkg':'y'}, {})
    def test_disabled_config_normalization(self):
        actual=config_values('# CONFIG_FOO is not set\nCONFIG_BAR=y\n')
        assert_config({'CONFIG_FOO':'n','CONFIG_BAR':'y'},actual)
    def test_invalid_config_is_rejected(self):
        with self.assertRaises(BuildError): config_values('rm -rf /')
    def test_overlay_path_escape_rejected(self):
        with self.assertRaises(BuildError): safe_path(ROOT/'files','../../outside')
    def test_overlay_rejects_secret_and_symlink(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config';p.write_text("option password 'not-a-real-password'\n")
            with self.assertRaises(BuildError): scan_tree(d)
            p.unlink();p.symlink_to('/etc/hosts')
            with self.assertRaises(BuildError): scan_tree(d)
    def test_secret_filename_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'authorized_keys').write_text('')
            with self.assertRaises(BuildError): scan_tree(d)
    def test_legacy_unknown_plugins_never_silently_disappear(self):
        names=installed_names('luci-app-ddns - 1.0\nunknown-proxy - 2\n')
        rows=propose(names,{'luci-app-ddns-go'},{'luci-app-ddns':{'replacement':['luci-app-ddns-go'],'reason':'migration'}})
        self.assertEqual(rows[0]['action'],'replace')
        self.assertEqual(rows[1]['action'],'review')
    def test_legacy_invalid_inventory_rejected(self):
        with self.assertRaises(BuildError): installed_names('nothing useful')
    def test_legacy_schema_excludes_credentials(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'network').write_text("config interface 'wan'\n option username 'secret-user'\n option password 'secret-value'\n")
            s=json.dumps(config_schema(d))
            self.assertIn('password',s)
            self.assertNotIn('secret-value',s)
            self.assertNotIn('secret-user',s)

    def test_manifest_must_include_requested_packages(self):
        from scripts.artifacts import verify_outputs
        with tempfile.TemporaryDirectory() as d:
            t=Path(d);(t/'image.bin').write_bytes(b'firmware')
            (t/'image.manifest').write_text('luci - 1\n')
            p=profile('x86-basic');p['required_artifacts']=['image.bin','*.manifest']
            with self.assertRaisesRegex(BuildError,'ca-bundle'):
                verify_outputs(t,p)
            (t/'image.manifest').write_text('luci - 1\nca-bundle - 1\nluci-i18n-base-zh-cn - 1\n')
            verify_outputs(t,p)
    def test_missing_image_is_fatal(self):
        from scripts.artifacts import verify_outputs
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaisesRegex(BuildError,'Missing required artifact'):
                verify_outputs(Path(d),profile('x86-basic'))

    def test_compiler_cache_uses_work_directory(self):
        values=requested_config(profile('x86-basic'),Path('/tmp/test-work'))
        self.assertEqual(values['CONFIG_CCACHE_DIR'],'"/tmp/test-work/ccache"')

    def test_private_data_cannot_be_selected_through_relative_overlay_paths(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'profiles').mkdir();(root/'files').mkdir();(root/'private').mkdir()
            (root/'profiles/leak.json').write_text(json.dumps({'name':'leak','fragments':[],'packages':[],'overlays':['files/../private']}))
            with patch('scripts.fwlib.ROOT',root):
                with self.assertRaisesRegex(BuildError,'approved firmware directory'):profile('leak')
