include $(TOPDIR)/rules.mk
PKG_NAME:=neko-l2vpn
PKG_VERSION:=1.0.0
PKG_RELEASE:=1
PKG_LICENSE:=MIT
include $(INCLUDE_DIR)/package.mk

define Package/neko-l2vpn
  SECTION:=net
  CATEGORY:=Network
  TITLE:=L2TPv3 over WireGuard with optional dedicated VLESS UDP transport
  DEPENDS:=+ip-full +kmod-l2tp-eth +kmod-wireguard +wireguard-tools +netifd +uci +python3-light +xray-core
endef

define Package/neko-l2vpn/conffiles
/etc/config/neko-l2vpn
endef

define Build/Compile
endef

define Package/neko-l2vpn/install
	$(INSTALL_DIR) $(1)/etc/config $(1)/etc/init.d $(1)/usr/libexec/neko-l2vpn $(1)/lib/netifd/proto
	$(INSTALL_CONF) ./files/neko-l2vpn.config $(1)/etc/config/neko-l2vpn
	$(INSTALL_BIN) ./files/neko-l2vpn.init $(1)/etc/init.d/neko-l2vpn
	$(INSTALL_BIN) ./files/l2vpn.py $(1)/usr/libexec/neko-l2vpn/l2vpn.py
	$(INSTALL_BIN) ./files/neko_l2tp.sh $(1)/lib/netifd/proto/neko_l2tp.sh
endef

$(eval $(call BuildPackage,neko-l2vpn))
