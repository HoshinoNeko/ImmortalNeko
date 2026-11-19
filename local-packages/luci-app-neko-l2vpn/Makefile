include $(TOPDIR)/rules.mk
PKG_NAME:=luci-app-neko-l2vpn
PKG_VERSION:=1.0.0
PKG_RELEASE:=1
PKG_LICENSE:=MIT
LUCI_TITLE:=L2TPv3 over WireGuard and dedicated VLESS transport
LUCI_DEPENDS:=+luci-base +neko-l2vpn +luci-proto-wireguard +luci-proto-vxlan
LUCI_PKGARCH:=all
include $(TOPDIR)/feeds/luci/luci.mk

# call BuildPackage - OpenWrt buildroot signature
