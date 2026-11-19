include $(TOPDIR)/rules.mk
PKG_NAME:=neko-observatory
PKG_VERSION:=1.0.0
PKG_RELEASE:=1
PKG_LICENSE:=MIT
include $(INCLUDE_DIR)/package.mk

define Package/neko-observatory
  SECTION:=net
  CATEGORY:=Network
  TITLE:=VLAN counters and read-only GECOOS AC collection
  DEPENDS:=+python3-light +python3-urllib +python3-openssl +ubus +uci +rpcd
endef

define Package/neko-observatory/conffiles
/etc/config/neko-observatory
endef

define Build/Compile
endef

define Package/neko-observatory/install
	$(INSTALL_DIR) $(1)/etc/config $(1)/etc/init.d $(1)/usr/libexec/neko-observatory $(1)/usr/libexec/rpcd $(1)/etc/neko-observatory $(1)/lib/upgrade/keep.d
	$(INSTALL_CONF) ./files/neko-observatory.config $(1)/etc/config/neko-observatory
	$(INSTALL_BIN) ./files/neko-observatory.init $(1)/etc/init.d/neko-observatory
	$(INSTALL_BIN) ./files/collector.py $(1)/usr/libexec/neko-observatory/collector.py
	$(INSTALL_BIN) ./files/neko.observatory $(1)/usr/libexec/rpcd/neko.observatory
	$(INSTALL_DATA) ./files/keep $(1)/lib/upgrade/keep.d/neko-observatory
	chmod 700 $(1)/etc/neko-observatory
endef

$(eval $(call BuildPackage,neko-observatory))
