These unmodified `Makefile` and `files/pptpd.init` fixtures come from
`immortalwrt/packages` commit `84bd86384928955b568988ca0e09e2c78c75173d`,
directory `net/pptpd`. They are distributed under their original GPL-2.0
license and retain the upstream copyright headers.

Tests apply the real feed patch to these fixtures, then run patched shell
functions with temporary paths and mocked procd/UCI helpers. They never run
a real PPTP server, modify the host network, or read real device credentials.

Fixture SHA256:

* `Makefile`: `fa001e7e47b228d4b904a669d473ba37b7b1a391b3ef9a8117694b6817d1019c`
* `files/pptpd.init`: `b470591d36762bf548ddd758b86e68c9cf7d9a6d452362540a16ac6ef690ca1c`

`COPYING` contains the GPL-2.0 text from the pinned main source LICENSES directory.
