import json
from pathlib import Path
import unittest

from scripts.fwlib import BuildError, ROOT, profile, requested_config
from scripts.migration_plan import make_plan


class MigrationPlanTests(unittest.TestCase):
    def test_local_port_is_not_reported_as_built_or_complete(self):
        plan = make_plan('luci-app-socat - 1\ntailscale - 2\nluci-app-missing - 3\n',
                         'Package: socat\nPackage: tailscale\n', {},
                         {'x86-ha': {'luci-app-socat', 'tailscale'}},
                         {'luci-app-socat': 'local-packages/luci-app-socat/Makefile'}, 'a'*40)
        rows = {r['old']: r for r in plan['plugins']}
        self.assertEqual(rows['luci-app-socat']['action'], 'port')
        self.assertEqual(rows['luci-app-socat']['selected_in'], ['x86-ha'])
        self.assertEqual(plan['unresolved_plugin_count'], 1)
        self.assertFalse(plan['all_plugins_preserved'])
        self.assertEqual(plan['standalone_services'][0]['selected_in'], ['x86-ha'])
        self.assertEqual(plan['profile_request_coverage']['x86-ha']['explicit_plugin_mapping_count'],1)
        self.assertEqual(plan['profile_request_coverage']['x86-ha']['defined_but_not_explicitly_requested'],0)

    def test_unavailable_replacement_cannot_be_counted_as_resolved(self):
        plan = make_plan('luci-app-old - 1\n', 'Package: luci\n',
                         {'luci-app-old': {'replacement': ['luci-app-new'], 'reason': 'replacement'}},
                         {'x86-ha': {'luci-app-new'}}, {}, 'a'*40)
        self.assertEqual(plan['unresolved_plugin_count'], 1)
        self.assertFalse(plan['all_plugins_preserved'])

    def test_empty_package_metadata_rejected(self):
        with self.assertRaises(BuildError):
            make_plan('luci-app-old - 1\n', '', {}, {}, {}, 'a'*40)

    def test_retained_components_and_existing_themes_are_selected_only_on_x86(self):
        x86 = requested_config(profile('x86-ha'))
        for package in ('luci-app-socat', 'luci-app-pptp-server', 'luci-app-wrtbwmon', 'luci-app-v2ray-server',
                        'neko-v2ray-server', 'v2ray-core', 'luci-app-filemanager', 'tailscale', 'kmod-bonding',
                        'luci-app-turboacc','neko-bbr','dnsproxy','kmod-tcp-bbr','kmod-nft-offload','kmod-nft-fullcone','luci-app-wechatpush'):
            self.assertEqual(x86['CONFIG_PACKAGE_'+package], 'y')
        self.assertEqual(x86['CONFIG_BUSYBOX_DEFAULT_NTPD'], 'y')
        for theme in ('argon','bootstrap','material'):
            self.assertEqual(x86['CONFIG_PACKAGE_luci-theme-'+theme], 'y')
        for name in ('x86-basic','r619ac-ha'):
            self.assertNotIn('CONFIG_PACKAGE_luci-theme-argon', requested_config(profile(name)))
        self.assertNotIn('CONFIG_PACKAGE_luci-app-filemanager', requested_config(profile('r619ac-ha')))
        for package in ('luci-app-v2ray-server','neko-v2ray-server','v2ray-core','python3-light',
                        'luci-app-turboacc','neko-bbr','dnsproxy','kmod-tcp-bbr','luci-app-wechatpush'):
            self.assertNotIn('CONFIG_PACKAGE_'+package,requested_config(profile('r619ac-ha')))

    def test_all_profiles_include_the_official_proxy_and_ddns_stack(self):
        for name in ('x86-basic', 'x86-ha', 'r619ac-basic', 'r619ac-ha'):
            config = requested_config(profile(name))
            for package in ('luci-app-homeproxy', 'sing-box', 'luci-app-ddns-go', 'ddns-go',
                            'luci-i18n-homeproxy-zh-cn', 'luci-i18n-ddns-go-zh-cn'):
                self.assertEqual(config['CONFIG_PACKAGE_'+package], 'y', (name, package))
            self.assertEqual(config['CONFIG_PACKAGE_dnsmasq'], 'n')
            self.assertEqual(config['CONFIG_PACKAGE_dnsmasq-full'], 'y')
            self.assertEqual(config['CONFIG_PACKAGE_dnsmasq_full_nftset'], 'y')

    def test_existing_x86_usb_nic_and_storage_drivers_are_not_applied_to_r619ac(self):
        x86=requested_config(profile('x86-ha'))
        backup=requested_config(profile('r619ac-ha'))
        for name in ('kmod-bnx2x','kmod-usb-net-aqc111','kmod-usb-net-cdc-ether',
                     'kmod-usb-net-rndis','kmod-usb-net-rtl8152-vendor','kmod-usb-printer','kmod-mmc','kmod-sdhci'):
            self.assertEqual(x86['CONFIG_PACKAGE_'+name],'y')
            self.assertNotIn('CONFIG_PACKAGE_'+name,backup)

    def test_ported_ui_packages_do_not_own_backend_configuration_or_service(self):
        for app,config in (('luci-app-socat','socat'),('luci-app-pptp-server','pptpd'),
                           ('luci-app-wrtbwmon',None),('luci-app-v2ray-server','v2ray_server'),
                           ('luci-app-turboacc',['turboacc','firewall','dnsproxy'])):
            root = ROOT/'local-packages'/app/'root'
            self.assertFalse((root/'etc/config').exists())
            self.assertFalse((root/'etc/init.d').exists())
            acl = json.loads((root/'usr/share/rpcd/acl.d'/f'{app}.json').read_text())[app]
            if config:
                self.assertEqual(acl['write'], {'uci': config if isinstance(config,list) else [config]})
            else:
                self.assertNotIn('write',acl)
