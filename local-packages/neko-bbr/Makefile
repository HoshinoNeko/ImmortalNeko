include $(TOPDIR)/rules.mk
PKG_NAME:=neko-bbr
PKG_VERSION:=1.0.0
PKG_RELEASE:=1
PKG_LICENSE:=MIT
include $(INCLUDE_DIR)/package.mk

define Package/neko-bbr
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Explicit BBR selection with previous-algorithm restoration
  DEPENDS:=+kmod-tcp-bbr +uci +ubox +busybox +flock
endef

define Package/neko-bbr/conffiles
/etc/config/turboacc
endef

define Build/Compile
endef

define Package/neko-bbr/install
	$(INSTALL_DIR) $(1)/etc/config $(1)/etc/init.d $(1)/usr/libexec/neko-bbr
	$(INSTALL_CONF) ./files/turboacc.config $(1)/etc/config/turboacc
	$(INSTALL_BIN) ./files/neko-bbr.init $(1)/etc/init.d/neko-bbr
	$(INSTALL_BIN) ./files/apply.sh $(1)/usr/libexec/neko-bbr/apply.sh
endef
$(eval $(call BuildPackage,neko-bbr))
