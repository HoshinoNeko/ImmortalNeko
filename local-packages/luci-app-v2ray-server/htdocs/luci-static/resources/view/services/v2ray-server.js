'use strict';
'require view';
'require form';
'require uci';

return view.extend({
	load: function() { return uci.load('v2ray_server'); },
	render: function() {
		const m = new form.Map('v2ray_server', _('V2Ray Server'),
			_('Configure listener addresses and credentials locally. Keep the generic V2Ray service disabled. Add firewall rules separately; this page does not open ports or change network interfaces.'));
		let s = m.section(form.TypedSection, 'global', _('Global settings'));
		s.anonymous = true;
		s.addremove = false;
		let o = s.option(form.Flag, 'enable', _('Enable'));
		o.default = '0'; o.rmempty = false;
		o = s.option(form.Flag, 'accept_lan', _('Allow private destinations'));
		o.description = _('Allow proxy clients to connect to private, loopback and link-local addresses.');
		o.default = '0'; o.rmempty = false;
		o = s.option(form.ListValue, 'loglevel', _('Log level'));
		for (const value of ['warning', 'error', 'info', 'debug', 'none']) o.value(value);
		o.default = 'warning';

		s = m.section(form.GridSection, 'user', _('Server entries'));
		s.anonymous = true; s.addremove = true;
		s.tab('basic', _('Basic settings'));
		s.tab('transport', _('Transport settings'));
		s.tab('tls', _('TLS settings'));
		function option(tab, type, name, title, depends, datatype) {
			const field = s.taboption(tab, type, name, title);
			field.retain = true;
			field.modalonly = !['enable', 'remarks', 'protocol', 'port'].includes(name);
			if (datatype) field.datatype = datatype;
			if (depends) for (const condition of depends) field.depends(condition);
			return field;
		}
		const active = [{enable: '1'}];
		const protocols = values => values.map(value => ({enable: '1', protocol: value}));
		const transports = value => [{enable: '1', transport: value}];
		o = option('basic', form.Flag, 'enable', _('Enable'));
		o.default = '0'; o.rmempty = false;
		option('basic', form.Value, 'remarks', _('Remarks'));
		o = option('basic', form.ListValue, 'protocol', _('Protocol'), active);
		for (const value of ['shadowsocks', 'vmess', 'vless', 'trojan', 'socks', 'http']) o.value(value);
		o.rmempty = false;
		o = option('basic', form.Value, 'port', _('Listen port'), active, 'port'); o.rmempty = false;
		o = option('basic', form.Flag, 'bind_local', _('Loopback only'), active);
		o.default = '0'; o.rmempty = false;
		o = option('basic', form.Value, 'listen', _('Listen IP address'), [{enable: '1', bind_local: '0'}], 'ipaddr("nomask")');
		o.description = _('Choose an address explicitly before enabling a listener. Loopback-only mode uses 127.0.0.1 when no address is supplied.');
		o.rmempty = false;
		o = option('basic', form.Value, 'level', _('User level'), active, 'range(0,4294967295)'); o.default = '0';
		o.validate = function(section, value) {
			const selected = this.map.lookupOption('protocol', section)[0].formvalue(section);
			return selected !== 'shadowsocks' || Number(value || 0) <= 255 ? true : _('Shadowsocks level must be between 0 and 255.');
		};
		o = option('basic', form.Value, 'password', _('Password'), protocols(['shadowsocks', 'trojan', 'socks', 'http']));
		o['password'] = true; o.rmempty = false;
		o = option('basic', form.Value, 'username', _('Username'), protocols(['socks', 'http'])); o.rmempty = false;
		o = option('basic', form.ListValue, 'method', _('Shadowsocks encryption'), protocols(['shadowsocks']));
		for (const value of ['aes-128-gcm', 'aes-256-gcm', 'chacha20-ietf-poly1305', 'chacha20-poly1305']) o.value(value);
		o.rmempty = false;
		o = option('basic', form.ListValue, 'ss_network', _('Shadowsocks network'), protocols(['shadowsocks']));
		for (const value of ['tcp,udp', 'tcp', 'udp']) o.value(value);
		o.default = 'tcp,udp'; o.rmempty = false;
		o = option('basic', form.DynamicList, 'uuid', _('UUIDs'), protocols(['vmess', 'vless'])); o.rmempty = false;
		o.validate = function(section, value) {
			const values = Array.isArray(value) ? value : [value];
			return values.length && values.every(item => typeof item === 'string' && /^[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$/.test(item)) ? true : _('Use canonical UUID values.');
		};
		o = option('basic', form.Value, 'alter_id', _('VMess alterId'), protocols(['vmess']), 'range(0,65535)'); o.default = '0';
		o = option('basic', form.Flag, 'socks_udp', _('SOCKS UDP'), protocols(['socks'])); o.default = '0'; o.rmempty = false;

		o = option('transport', form.ListValue, 'transport', _('Transport'), active);
		for (const value of ['tcp', 'ws', 'h2', 'kcp', 'quic', 'grpc']) o.value(value);
		o.default = 'tcp'; o.rmempty = false;
		o = option('transport', form.ListValue, 'tcp_guise', _('TCP header'), transports('tcp'));
		o.value('none'); o.value('http'); o.default = 'none';
		for (const [name, title] of [['ws_path', _('WebSocket path')], ['ws_host', _('WebSocket Host')]])
			option('transport', form.Value, name, title, transports('ws'));
		option('transport', form.Value, 'h2_path', _('HTTP/2 path'), transports('h2'));
		option('transport', form.DynamicList, 'h2_host', _('HTTP/2 hosts'), transports('h2'));
		option('transport', form.Value, 'grpc_service_name', _('gRPC service name'), transports('grpc'));
		for (const transport of ['kcp', 'quic']) {
			o = option('transport', form.ListValue, transport + '_guise', _('Packet header'), transports(transport));
			for (const value of ['none', 'srtp', 'utp', 'wechat-video', 'dtls', 'wireguard']) o.value(value);
			o.default = 'none';
		}
		for (const [name, title, datatype] of [
			['kcp_mtu', _('KCP MTU'), 'range(576,1460)'], ['kcp_tti', _('KCP TTI'), 'range(10,100)'],
			['kcp_uplink', _('KCP uplink capacity'), 'range(0,10000)'], ['kcp_downlink', _('KCP downlink capacity'), 'range(0,10000)'],
			['kcp_read_buffer', _('KCP read buffer (MiB)'), 'range(0,1024)'], ['kcp_write_buffer', _('KCP write buffer (MiB)'), 'range(0,1024)']
		]) option('transport', form.Value, name, title, transports('kcp'), datatype);
		option('transport', form.Flag, 'kcp_congestion', _('KCP congestion control'), transports('kcp'));
		o = option('transport', form.Value, 'kcp_seed', _('KCP seed'), transports('kcp')); o['password'] = true;
		o = option('transport', form.ListValue, 'quic_security', _('QUIC encryption'), transports('quic'));
		for (const value of ['none', 'aes-128-gcm', 'chacha20-poly1305']) o.value(value);
		o.default = 'none';
		o = option('transport', form.Value, 'quic_key', _('QUIC credential'), transports('quic')); o['password'] = true;

		o = option('tls', form.Flag, 'tls', _('Enable TLS'), active); o.default = '0'; o.rmempty = false;
		for (const [name, title] of [['tls_cert', _('Certificate file')], ['tls_key', _('TLS keyfile')]]) {
			o = option('tls', form.Value, name, title, [{enable: '1', tls: '1'}]); o.rmempty = false;
			o.validate = function(section, value) {
				return value && value.startsWith('/') && !/[\x00-\x1f\x7f]/.test(value) ? true : _('Use an absolute local file path.');
			};
		}
		option('tls', form.Value, 'tls_servername', _('TLS server name'), [{enable: '1', tls: '1'}]);
		option('tls', form.DynamicList, 'tls_alpn', _('ALPN protocols'), [{enable: '1', tls: '1'}]);
		return m.render();
	}
});
