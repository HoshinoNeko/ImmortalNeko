include $(TOPDIR)/rules.mk
PKG_NAME:=firmware-ha
PKG_VERSION:=0.1.0
PKG_RELEASE:=1
PKG_LICENSE:=MIT
PKG_MAINTAINER:=Local firmware maintainer
include $(INCLUDE_DIR)/package.mk

define Package/firmware-ha
  SECTION:=net
  CATEGORY:=Network
  TITLE:=Local dual router HA controller
  DEPENDS:=+keepalived +ip-full +iputils-ping +uci +ubus +jsonfilter
endef

define Package/firmware-ha/conffiles
/etc/config/firmware-ha
endef

define Build/Compile
endef

define Package/firmware-ha/install
	$(INSTALL_DIR) $(1)/etc/config $(1)/etc/init.d $(1)/etc/uci-defaults
	$(INSTALL_CONF) ./files/firmware-ha.config $(1)/etc/config/firmware-ha
	$(INSTALL_BIN) ./files/firmware-ha.init $(1)/etc/init.d/firmware-ha
	$(INSTALL_BIN) ./files/90-firmware-ha.sh $(1)/etc/uci-defaults/90-firmware-ha
	$(INSTALL_DIR) $(1)/usr/libexec/firmware-ha $(1)/usr/sbin
	$(INSTALL_BIN) ./files/lib.sh $(1)/usr/libexec/firmware-ha/lib.sh
	$(INSTALL_BIN) ./files/render.sh $(1)/usr/libexec/firmware-ha/render.sh
	$(INSTALL_BIN) ./files/check.sh $(1)/usr/libexec/firmware-ha/check.sh
	$(INSTALL_BIN) ./files/notify.sh $(1)/usr/libexec/firmware-ha/notify.sh
	$(INSTALL_BIN) ./files/ha-status.sh $(1)/usr/sbin/firmware-ha-status
endef
$(eval $(call BuildPackage,firmware-ha))
