Unmodified source fixtures from the official ImmortalWrt LuCI feed commit
`d6167ea0645cbd1327708d85f94824f42d0eb872`, WeChatPush 3.6.12.
The upstream project is <https://github.com/tty228/luci-app-wechatpush> (GPL-2.0).
Original source bytes are SHA256-recorded in `manifest.json` and checked before
the real x86-ha feed patch is applied in a temporary directory.

Tests extract configuration functions and mock UCI/procd/HA. They do not run the
notification loop, contact providers, send messages, or change host services.
