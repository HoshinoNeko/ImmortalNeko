include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-wrtbwmon
PKG_VERSION:=1.0.0
PKG_RELEASE:=1
PKG_LICENSE:=MIT

LUCI_TITLE:=Per-device traffic totals and sampled rates using nlbwmon
LUCI_DEPENDS:=+luci-base +luci-app-nlbwmon
LUCI_PKGARCH:=all

# The official nlbwmon package owns configuration, init and accounting data.
include $(TOPDIR)/feeds/luci/luci.mk
