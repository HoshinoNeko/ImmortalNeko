'use strict';
'require view';
'require form';
'require uci';

function values(value) {
	return Array.isArray(value) ? value : (value ? value.trim().split(/\s+/) : []);
}

function singleLine(section, value) {
	return /[\x00-\x1f\x7f]/.test(value || '') ? _('Control characters are not supported.') : true;
}

return view.extend({
	load: function() {
		return uci.load('pptpd');
	},

	render: function() {
		var m = new form.Map('pptpd', _('PPTP Server'),
			_('Configure server and client addresses locally. Firewall rules for TCP 1723 and GRE must be configured separately.'));
		var s = m.section(form.NamedSection, 'pptpd', 'service', _('Server'));
		var o = s.option(form.Flag, 'enabled', _('Enable'));
		// Missing enabled uses the official backend default; the image sets it to 0.
		o.default = '1';
		o.rmempty = false;

		o = s.option(form.Value, 'localip', _('Server IPv4 address'));
		o.datatype = 'ip4addr';
		o.depends('enabled', '1');
		o.retain = true;
		o.rmempty = false;

		o = s.option(form.Value, 'remoteip', _('Client address pool'));
		o.description = _('Comma-separated IPv4 addresses or ranges in pptpd.conf syntax.');
		o.validate = singleLine;
		o.depends('enabled', '1');
		o.retain = true;
		o.rmempty = false;

		o = s.option(form.DynamicList, 'remotedns', _('DNS servers offered to clients'));
		o.datatype = 'ip4addr';
		o.cfgvalue = function(section) { return values(uci.get('pptpd', section, 'remotedns')); };
		o.depends('enabled', '1');
		o.retain = true;

		o = s.option(form.DynamicList, 'mppe', _('MPPE options'));
		o.cfgvalue = function(section) {
			var value = uci.get('pptpd', section, 'mppe');
			return value == null ? ['nomppe-40', 'nomppe-stateful', 'require-mppe-128'] : values(value);
		};
		o.validate = singleLine;
		o.depends('enabled', '1');
		o.retain = true;

		o = s.option(form.Flag, 'logwtmp', _('Record logins in wtmp'));
		o.default = '0';

		s = m.section(form.TypedSection, 'login', _('Accounts'));
		s.anonymous = true;
		s.addremove = true;

		o = s.option(form.Value, 'username', _('Username'));
		o.validate = singleLine;
		o.rmempty = false;

		o = s.option(form.Value, 'password', _('Password'));
		o['password'] = true;
		o.validate = singleLine;
		o.rmempty = false;

		o = s.option(form.Value, 'remoteip', _('Allowed client addresses'));
		o.description = _('Leave empty for any address, or use the PPP address-list syntax.');
		o.validate = singleLine;
		return m.render();
	}
});
