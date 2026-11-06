include $(TOPDIR)/rules.mk
PKG_NAME:=neko-v2ray-server
PKG_VERSION:=1.0.0
PKG_RELEASE:=1
PKG_LICENSE:=MIT
include $(INCLUDE_DIR)/package.mk

define Package/neko-v2ray-server
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Legacy V2Ray Server configuration adapter
  DEPENDS:=+v2ray-core +python3-light +uci
endef

define Package/neko-v2ray-server/conffiles
/etc/config/v2ray_server
endef

define Build/Compile
endef

define Package/neko-v2ray-server/install
	$(INSTALL_DIR) $(1)/etc/config $(1)/etc/init.d $(1)/usr/libexec/neko-v2ray-server
	$(INSTALL_CONF) ./files/v2ray_server.config $(1)/etc/config/v2ray_server
	$(INSTALL_BIN) ./files/v2ray_server.init $(1)/etc/init.d/v2ray_server
	$(INSTALL_BIN) ./files/render.py $(1)/usr/libexec/neko-v2ray-server/render.py
endef
$(eval $(call BuildPackage,neko-v2ray-server))
