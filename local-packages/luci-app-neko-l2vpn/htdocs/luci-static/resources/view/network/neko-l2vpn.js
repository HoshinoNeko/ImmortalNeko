'use strict';
'require view';
'require form';
'require uci';
'require tools.widgets as widgets';

return view.extend({
    load: function() { return uci.load('neko-l2vpn'); },
    render: function() {
        const m = new form.Map('neko-l2vpn', _('Layer 2 VPN'),
            _('Configure WireGuard and L2TPv3 or VXLAN in Network → Interfaces. Enable this transport only when WireGuard needs VLESS. Choose a dedicated LAN or SSID for bridging.'));
        const s = m.section(form.NamedSection, 'main', 'transport', _('WireGuard over VLESS'));
        function option(type, name, title, dependencies, datatype) {
            const o = s.option(type, name, title);
            o.retain = true;
            if (dependencies) for (const dep of dependencies) o.depends(dep);
            if (datatype) o.datatype = datatype;
            return o;
        }
        const client = [{enabled: '1', role: 'client'}];
        const server = [{enabled: '1', role: 'server'}];
        const active = [{enabled: '1'}];
        let o = option(form.Flag, 'enabled', _('Enable VLESS transport'));
        o.default = '0'; o.rmempty = false;
        o = option(form.ListValue, 'role', _('Role'), active);
        o.value('client', _('Dorm client')); o.value('server', _('Home server')); o.default = 'client';
        o = option(form.ListValue, 'security', _('Transport security'), active);
        o.value('tls', 'TLS'); o.value('reality', 'REALITY'); o.default = 'tls';
        o = option(form.Value, 'uuid', _('VLESS UUID'), active);
        o['password'] = true; o.rmempty = false;
        o.validate = function(_section, value) {
            return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value || '') || _('Enter a complete UUID.');
        };
        o = option(form.ListValue, 'flow', _('VLESS flow'), active);
        o.value('', _('None')); o.value('xtls-rprx-vision', 'XTLS Vision'); o.default = '';
        o = option(form.Value, 'server', _('VLESS server address'), client, 'host'); o.rmempty = false;
        o = option(form.Value, 'server_port', _('VLESS TCP port'), active, 'port'); o.default = '443'; o.rmempty = false;
        o = option(form.Value, 'server_name', _('TLS / REALITY server name'), active, 'host'); o.rmempty = false;
        o = option(widgets.DeviceSelect, 'egress_device', _('WAN egress device'), client);
        o.nocreate = true; o.multiple = false; o.rmempty = false;
        o.description = _('Select the actual WAN device, such as a PPP device. The VLESS connection must remain outside WireGuard.');
        o = option(form.Value, 'proxy_port', _('Local UDP forwarding port'), client, 'port'); o.default = '51821'; o.rmempty = false;
        o.description = _('Point the dorm WireGuard peer endpoint to 127.0.0.1 and this port.');
        o = option(form.Value, 'listen_address', _('Home listen address'), server, 'ipaddr("nomask")'); o.rmempty = false;
        o = option(form.Value, 'target_address', _('Home WireGuard destination IP'), active, 'ipaddr("nomask")'); o.default = '127.0.0.1'; o.rmempty = false;
        o.description = _('Both ends must use the same destination IP and UDP port. On a home Xray server, loopback normally reaches its local WireGuard listener.');
        o = option(form.Value, 'target_port', _('Home WireGuard UDP port'), active, 'port'); o.default = '51820'; o.rmempty = false;
        const tlsServer = [{enabled: '1', role: 'server', security: 'tls'}];
        o = option(form.Value, 'certificate_file', _('TLS certificate file'), tlsServer); o.rmempty = false;
        o = option(form.Value, 'certificate_key_file', _('TLS private-key file'), tlsServer); o.rmempty = false;
        option(form.Value, 'ca_certificate_file', _('Optional private CA certificate file'), [{enabled: '1', role: 'client', security: 'tls'}]);
        const realityClient = [{enabled: '1', role: 'client', security: 'reality'}];
        o = option(form.Value, 'reality_public_key', _('REALITY public key'), realityClient); o.rmempty = false;
        o = option(form.Value, 'reality_short_id', _('REALITY short ID'), [{enabled: '1', security: 'reality'}]);
        o.validate = function(_section, value) { return /^(?:[0-9a-f]{2}){0,8}$/i.test(value || '') || _('Use up to 16 hexadecimal characters in pairs.'); };
        const realityServer = [{enabled: '1', role: 'server', security: 'reality'}];
        o = option(form.Value, 'reality_private_key_file', _('REALITY private-key file'), realityServer); o.rmempty = false;
        o = option(form.Value, 'reality_target', _('REALITY target host:port'), realityServer); o.rmempty = false;
        return m.render();
    }
});
