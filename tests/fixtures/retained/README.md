These unmodified fixtures are from the locked official ImmortalWrt feeds:

* `luci/`: `immortalwrt/luci` commit `d6167ea0645cbd1327708d85f94824f42d0eb872`.
* `packages/`: `immortalwrt/packages` commit `84bd86384928955b568988ca0e09e2c78c75173d`.

Paths are relative to each feed root. `manifest.json` records the SHA256 of
every upstream file; tests verify these bytes before applying the real patches.
Original copyright and license headers remain in place. GPL-2.0 and Apache-2.0
license texts are included alongside this document.

Tests apply patches in temporary directories and execute shell scripts with
temporary file paths and mocked UCI/service helpers. They do not change the
host network, run VPN daemons, or use device data. Example credentials in the
unmodified upstream config fixtures are public test data. The build patches
remove those defaults before packaging; test fixtures never enter the rootfs.
