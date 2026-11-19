'use strict';
'require view';
'require form';

return view.extend({
	render: function() {
		var m = new form.Map('neko-observatory', _('Dashboard collection'),
			_('Only interface counters and read-only AC queries are collected. Credentials stay in a root-only file; the browser never receives them.'));
		var s = m.section(form.NamedSection, 'main', 'observatory');
		var o = s.option(form.Flag, 'enabled', _('Enable collection'));
		o.default = '1'; o.rmempty = false;
		o = s.option(form.Flag, 'auto_discover', _('Discover internal VLANs'));
		o.description = _('Detect VLAN interfaces in firewall zones without masquerading. WAN and tunnel interfaces are excluded. Add explicit interfaces below when needed.');
		o.default = '1'; o.rmempty = false;
		o = s.option(form.Value, 'interval', _('Counter interval (seconds)'));
		o.datatype = 'range(2,15)'; o.default = '5'; o.rmempty = false;
		o = s.option(form.Value, 'history_points', _('History points per VLAN'));
		o.description = _('Stored in RAM only. At 5 seconds, 360 points cover 30 minutes. Totals and history restart with the collector.');
		o.datatype = 'range(60,720)'; o.default = '360'; o.rmempty = false;
		o = s.option(form.Flag, 'ac_enabled', _('Collect GECOOS AC'));
		o.default = '1'; o.rmempty = false;
		o = s.option(form.Value, 'ac_url', _('AC address'));
		o.validate = function(section, value) {
			return /^https?:\/\/(?:[a-zA-Z0-9.-]+|\[[0-9a-fA-F:]+\])(?::[0-9]{1,5})?\/?$/.test(value) || _('Enter an HTTP or HTTPS origin without credentials or a path.');
		};
		o.rmempty = false;
		o = s.option(form.Value, 'ac_password_file', _('AC credential file'));
		o.description = _('Absolute path to a root-owned file with mode 600 containing the AC login password. Provision it locally; keep credentials out of UCI or the firmware.');
		o.datatype = 'file'; o.rmempty = false;
		o = s.option(form.Value, 'ac_interval', _('AC interval (seconds)'));
		o.datatype = 'range(15,3600)'; o.default = '30'; o.rmempty = false;
		o = s.option(form.Value, 'ac_stale_after', _('AC stale threshold (seconds)'));
		o.datatype = 'range(30,86400)'; o.default = '120'; o.rmempty = false;
		o = s.option(form.Value, 'ap_stale_after', _('AP report stale threshold (seconds)'));
		o.datatype = 'range(30,86400)'; o.default = '180'; o.rmempty = false;
		s = m.section(form.TypedSection, 'vlan', _('Explicit VLAN interfaces'));
		s.anonymous = true; s.addremove = true;
		o = s.option(form.Value, 'interface', _('Logical interface'));
		o.datatype = 'uciname'; o.rmempty = false;
		o.description = _('Use the interface name from Network → Interfaces. Interfaces sharing a netdevice are counted once.');
		o = s.option(form.Value, 'label', _('Display name'));
		return m.render();
	}
});
