'use strict';
'require view';
'require form';
'require uci';

return view.extend({
	load: function() {
		return uci.load('socat');
	},

	render: function() {
		var m = new form.Map('socat', _('Socat'),
			_('Manage the official Socat service. Firewall rules must be configured separately.'));
		var s = m.section(form.TypedSection, 'socat', _('Instances'));
		s.anonymous = false;
		s.addremove = true;

		var o = s.option(form.Flag, 'enable', _('Enable'));
		// Match the official backend when an existing section omits enable.
		o.default = '1';
		o.rmempty = false;

		o = s.option(form.Value, 'user', _('Run as user'));
		o.placeholder = 'root';
		o.description = _('If empty, the official service runs as root.');
		o.rmempty = true;

		o = s.option(form.ListValue, '_representation', _('Argument format'));
		o.value('string', _('Legacy argument string'));
		o.value('list', _('Separate arguments'));
		o.cfgvalue = function(section) {
			return Array.isArray(uci.get('socat', section, 'SocatOptions')) ? 'list' : 'string';
		};
		// Representation controls the form, not the backend UCI schema.
		o.write = o.remove = function() {};

		o = s.option(form.Value, '_legacy_options', _('Socat arguments'));
		o.depends('_representation', 'string');
		o.description = _('The official service splits this string on whitespace. Use separate arguments when an argument contains spaces.');
		o.rmempty = false;
		o.cfgvalue = function(section) {
			var value = uci.get('socat', section, 'SocatOptions');
			return typeof value === 'string' ? value : '';
		};
		o.write = function(section, value) {
			uci.set('socat', section, 'SocatOptions', value);
		};
		o.remove = function() {};

		o = s.option(form.DynamicList, '_argument_list', _('Socat arguments'));
		o.depends('_representation', 'list');
		o.description = _('Each entry is one argument, passed directly to Socat. Do not add shell quoting.');
		o.rmempty = false;
		o.cfgvalue = function(section) {
			var value = uci.get('socat', section, 'SocatOptions');
			return Array.isArray(value) ? value : [];
		};
		o.write = function(section, value) {
			uci.set('socat', section, 'SocatOptions', value);
		};
		o.remove = function() {};
		return m.render();
	}
});
