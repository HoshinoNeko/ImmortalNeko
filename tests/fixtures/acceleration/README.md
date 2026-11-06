Unmodified upstream fixture bytes are recorded in `manifest.json` and verified
before tests apply the real profile patches.

* `package/`: official ImmortalWrt source commit
  `4fc16f2985a358bd43bb522e43f05395fcbd6ed5`.
* `feeds/packages/`: official packages feed commit
  `84bd86384928955b568988ca0e09e2c78c75173d`.

Original headers remain in place. The source tree's GPL-2.0 text and the
DNSProxy package's Apache-2.0 text are included. Tests use temporary files,
actual OpenWrt configuration helpers, and mocked procd/sysctl/module loading.
They never change the host kernel, network or resolver configuration.
