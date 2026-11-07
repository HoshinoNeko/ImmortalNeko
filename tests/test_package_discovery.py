from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.fwlib import BuildError, ROOT, profile
from scripts.sources import install_files, validate_local_packages


class PackageDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for parent in ('local-packages', 'themes/packages'):
            (self.root/parent).mkdir(parents=True)

    def package(self, parent, name, text):
        directory = self.root/parent/name
        directory.mkdir()
        (directory/'Makefile').write_text(text)
        return directory

    def test_luci_include_alone_cannot_register_a_package(self):
        for parent in ('local-packages', 'themes/packages'):
            with self.subTest(parent=parent):
                directory = self.package(parent, 'luci-app-missing',
                                         'include $(TOPDIR)/feeds/luci/luci.mk\n')
                with patch('scripts.sources.ROOT', self.root):
                    with self.assertRaisesRegex(BuildError, 'invisible.*luci-app-missing/Makefile'):
                        validate_local_packages()
                (directory/'Makefile').unlink()

    def test_native_registration_and_luci_signature_are_discoverable(self):
        for i, text in enumerate(('# call BuildPackage - OpenWrt buildroot signature\n',
                                  '$(eval $(call BuildPackage,backend))\n',
                                  '$(eval $(call KernelPackage,driver))\n',
                                  '$(eval $(call Build/DefaultTargets))\n')):
            self.package('local-packages', f'package-{i}', text)
        self.package('themes/packages', 'luci-theme-example',
                     '# call BuildPackage - OpenWrt buildroot signature\n')
        with patch('scripts.sources.ROOT', self.root):
            validate_local_packages()

    def test_validation_command_checks_discovery_before_source_download(self):
        self.package('local-packages', 'luci-app-missing',
                     'include $(TOPDIR)/feeds/luci/luci.mk\n')
        from scripts.build import validate
        with patch('scripts.sources.ROOT', self.root):
            with self.assertRaisesRegex(BuildError, 'invisible.*luci-app-missing/Makefile'):
                validate()

    def test_installed_packages_match_pinned_buildroot_grep_rule(self):
        src = self.root/'source'
        install_files(src, profile('x86-ha'))
        makefiles = sorted((src/'package/custom').glob('*/Makefile'))
        # Exact ERE used by locked include/scan.mk; includes are not expanded.
        result = subprocess.run(['grep', '-aEl',
                                 'call (Build/DefaultTargets|BuildPackage|KernelPackage)',
                                 *map(str, makefiles)], text=True, capture_output=True, check=True)
        discovered = {Path(line).parent.name for line in result.stdout.splitlines()}
        self.assertEqual(discovered, {f.parent.name for f in makefiles})
        for makefile in (ROOT/'local-packages').glob('luci-app-*/Makefile'):
            self.assertIn(makefile.parent.name, discovered)


if __name__ == '__main__':
    unittest.main()
