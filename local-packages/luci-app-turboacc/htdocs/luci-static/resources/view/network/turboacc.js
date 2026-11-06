'use strict';
'require view';
'require form';
'require uci';
'require fs';

function retained(value) {
	return value == null ? '\u2014' : String(value);
}

return view.extend({
	load: function() {
		return Promise.all([
			uci.load('turboacc'), uci.load('firewall'), uci.load('dnsproxy'),
			L.resolveDefault(fs.read('/proc/sys/net/ipv4/tcp_congestion_control'), '\u2014'),
			L.resolveDefault(fs.read('/proc/sys/net/ipv4/tcp_available_congestion_control'), '\u2014')
		]);
	},

	render: function(data) {
		const maps = [];
		let m = new form.Map('turboacc', _('Turbo ACC'),
			_('Legacy offload values are reference data. Select changes in the actual firewall settings below. SFE is replaced by nftables flow offloading; MediaTek WED requires different hardware.'));
		maps.push(m);
		let s = m.section(form.TypedSection, 'turboacc', _('TCP congestion control'));
		s.anonymous = true; s.addremove = false;
		let o = s.option(form.DummyValue, '_current', _('Algorithm at page load'));
		o.cfgvalue = () => data[3].trim();
		o = s.option(form.DummyValue, '_available', _('Registered algorithms at page load'));
		o.cfgvalue = () => data[4].trim();
		o = s.option(form.Flag, 'bbr_cca', _('Manage BBR for new local TCP connections'));
		o.default = '0'; o.rmempty = false;
		o.description = _('Enabling records the previous algorithm. Disabling restores that value when the current value is still managed BBR; a different manual selection is preserved. Forwarded clients choose their own TCP algorithm.');
		o = s.option(form.DummyValue, '_legacy', _('Legacy reference values'));
		o.cfgvalue = section => [
			[_('Software offload'), 'sw_flow'], [_('Hardware offload'), 'hw_flow'],
			[_('FullCone mode'), 'fullcone_nat'], [_('DNS cache'), 'dns_caching'],
			['SFE', 'sfe_flow'], ['WED', 'hw_wed']
		].map(item => item[0] + ': ' + retained(uci.get('turboacc', section, item[1]))).join('; ');

		m = new form.Map('firewall', _('Firewall acceleration'),
			_('Keep current settings leaves firewall values untouched, including legacy values that still need migration. Hardware offload needs driver support. Check SQM, proxy routing and traffic accounting after enabling offload.'));
		maps.push(m);
		s = m.section(form.TypedSection, 'defaults');
		s.anonymous = true; s.addremove = false;
		o = s.option(form.DummyValue, '_current_flow', _('Configured offload values'));
		o.cfgvalue = section => retained(uci.get('firewall', section, 'flow_offloading')) + ' / ' + retained(uci.get('firewall', section, 'flow_offloading_hw'));
		if (L.hasSystemFeature('offloading')) {
			o = s.option(form.ListValue, '_set_flow', _('Change flow offloading'));
			o.value('keep', _('Keep current settings')); o.value('0', _('Disabled'));
			o.value('1', _('Software offload')); o.value('2', _('Hardware offload'));
			o.cfgvalue = () => 'keep'; o.rmempty = false;
			o.write = function(section, value) {
				if (value === 'keep') return;
				if (!['0','1','2'].includes(value)) throw new Error('Invalid offload selection');
				uci.set('firewall', section, 'flow_offloading', value === '0' ? '0' : '1');
				uci.set('firewall', section, 'flow_offloading_hw', value === '2' ? '1' : '0');
			};
			o.remove = function() {};
		}
		o = s.option(form.DummyValue, '_current_fullcone', _('Configured FullCone value'));
		o.cfgvalue = section => retained(uci.get('firewall', section, 'fullcone'));
		if (L.hasSystemFeature('fullcone')) {
			o = s.option(form.ListValue, '_set_fullcone', _('Change IPv4 FullCone NAT'));
			o.value('keep', _('Keep current settings')); o.value('0', _('Disabled')); o.value('1', _('Enabled'));
			o.description = _('Legacy modes 1 and 2 used a different implementation. Choose the new policy explicitly after checking NAT behavior.');
			o.cfgvalue = () => 'keep'; o.rmempty = false;
			o.write = function(section, value) {
				if (value === 'keep') return;
				if (!['0','1'].includes(value)) throw new Error('Invalid FullCone selection');
				uci.set('firewall', section, 'fullcone', value);
			};
			o.remove = function() {};
		}

		m = new form.Map('dnsproxy', _('DNS caching'),
			_('Choose upstream resolvers and listener settings before enabling. Configure forwarding in the appropriate DHCP/DNS instance separately; existing DNS servers and network interfaces are preserved. Encrypted upstreams may need explicit bootstrap resolvers.'));
		maps.push(m);
		s = m.section(form.NamedSection, 'global', 'dnsproxy', _('Resolver'));
		o = s.option(form.Flag, 'enabled', _('Enable DNSProxy')); o.default = '0'; o.rmempty = false;
		o.validate = function(section, value) {
			if (value !== '1') return true;
			const field = this.map.lookupOption('upstream', 'servers')[0];
			const configured = field ? field.formvalue('servers') : uci.get('dnsproxy', 'servers', 'upstream');
			return L.toArray(configured).some(item => String(item).trim()) ? true : _('Configure at least one upstream resolver.');
		};
		o = s.option(form.DynamicList, 'listen_addr', _('Listener addresses')); o.datatype = 'ipaddr("nomask")';
		o = s.option(form.DynamicList, 'listen_port', _('Listener ports')); o.datatype = 'port';
		o = s.option(form.ListValue, 'upstream_mode', _('Upstream mode'));
		o.value('', _('Core default')); o.value('load_balance', _('Load balance')); o.value('parallel', _('Parallel')); o.value('fastest_addr', _('Fastest address'));
		s = m.section(form.NamedSection, 'servers', 'dnsproxy', _('Upstream resolvers'));
		for (const [name, title] of [['upstream', _('Upstreams')], ['bootstrap', _('Bootstrap resolvers')], ['fallback', _('Fallback resolvers')]]) {
			o = s.option(form.DynamicList, name, title);
			o.description = _('Use DNSProxy upstream syntax, including encrypted resolver URLs or an upstream file.');
		}
		s = m.section(form.NamedSection, 'cache', 'dnsproxy', _('Cache'));
		o = s.option(form.Flag, 'enabled', _('Enable cache')); o.default = '0'; o.rmempty = false;
		for (const [name, title] of [['size', _('Cache size (bytes)')], ['min_ttl', _('Minimum TTL (seconds)')], ['max_ttl', _('Maximum TTL (seconds)')]]) {
			o = s.option(form.Value, name, title); o.datatype = 'uinteger';
		}
		o = s.option(form.Flag, 'cache_optimistic', _('Optimistic cache')); o.default = '0'; o.rmempty = false;
		s = m.section(form.NamedSection, 'bogus_nxdomain', 'dnsproxy', _('Bogus response addresses'));
		o = s.option(form.DynamicList, 'ip_addr', _('Return NXDOMAIN for these addresses')); o.datatype = 'ipaddr("nomask")';
		return Promise.all(maps.map(map => map.render())).then(nodes => E('div', {}, nodes));
	}
});
