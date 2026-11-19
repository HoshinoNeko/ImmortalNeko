Custom ImmortalWrt build. Each profile archive contains actual package manifests,
resolved config, source/feed commits, build-info.json and SHA256SUMS.
All profiles include HomeProxy/Sing-box and ddns-go; proxy nodes, DDNS domains and
credentials must be configured locally and are not embedded in the images.

Installation and HA deployment require the hardware and topology checks in README.md.
LEDE 18.06 configuration must be migrated, not blindly restored. HA is disabled
until local runtime configuration and credentials have been provisioned.
