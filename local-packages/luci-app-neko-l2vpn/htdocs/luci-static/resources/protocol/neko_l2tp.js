'use strict';
'require form';
'require network';
'require tools.widgets as widgets';

network.registerPatternVirtual(/^nl2-.+$/);

return network.registerProtocol('neko_l2tp', {
    getI18n: function() { return _('L2TPv3 over WireGuard'); },
    getIfname: function() { return this._ubus('l3_device') || 'nl2-' + this.sid; },
    getPackageName: function() { return 'neko-l2vpn'; },
    isFloating: function() { return true; },
    isVirtual: function() { return true; },
    getDevices: function() { return null; },
    containsDevice: function(ifname) { return network.getIfnameOf(ifname) === this.getIfname(); },
    renderFormOptions: function(s) {
        function field(name, title, datatype) {
            const o = s.taboption('general', form.Value, name, title);
            o.datatype = datatype; o.rmempty = false;
            return o;
        }
        let o = s.taboption('general', widgets.NetworkSelect, 'tunlink', _('WireGuard interface'));
        o.exclude = this.sid; o.nocreate = true; o.rmempty = false;
        o.description = _('Use a configured kernel WireGuard interface. Its peer Allowed IPs must cover the remote tunnel address.');
        field('ipaddr', _('Local WireGuard IPv4 address'), 'ip4addr("nomask")');
        field('peeraddr', _('Remote WireGuard IPv4 address'), 'ip4addr("nomask")');
        field('tunnel_id', _('Local tunnel ID'), 'range(1,4294967295)');
        field('peer_tunnel_id', _('Remote tunnel ID'), 'range(1,4294967295)');
        field('session_id', _('Local session ID'), 'range(1,4294967295)');
        field('peer_session_id', _('Remote session ID'), 'range(1,4294967295)');
        field('local_port', _('Local L2TP UDP port'), 'port').default = '1701';
        field('peer_port', _('Remote L2TP UDP port'), 'port').default = '1701';
        o = field('mtu', _('L2 MTU'), 'range(1280,9000)');
        o.placeholder = '1360';
        o.description = _('Choose an L2 MTU at least 50 bytes below WireGuard MTU. Use an interface name of at most 11 characters; bridge its nl2- device into a dedicated LAN.');
    }
});
