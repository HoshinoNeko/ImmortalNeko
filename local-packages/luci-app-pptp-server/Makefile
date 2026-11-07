include $(TOPDIR)/rules.mk

PKG_NAME:=luci-app-pptp-server
PKG_VERSION:=1.0.0
PKG_RELEASE:=1
PKG_LICENSE:=MIT

LUCI_TITLE:=LuCI interface for the official PPTP server
LUCI_DEPENDS:=+luci-base +pptpd
LUCI_PKGARCH:=all

# Config and init files remain owned by the pinned official pptpd package.
include $(TOPDIR)/feeds/luci/luci.mk

# call BuildPackage - OpenWrt buildroot signature
