include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-socat
PKG_VERSION:=1.0.0
PKG_RELEASE:=1
PKG_LICENSE:=MIT

LUCI_TITLE:=LuCI interface for the official Socat service
LUCI_DEPENDS:=+luci-base +socat
LUCI_PKGARCH:=all

# Use the locked official backend. This package owns no socat config/init files.
include $(TOPDIR)/feeds/luci/luci.mk

# call BuildPackage - OpenWrt buildroot signature
