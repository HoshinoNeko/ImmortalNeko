'use strict';
'require view';
'require rpc';
'require poll';
'require dom';
'require neko.observatory as obs';

var callStatus = rpc.declare({ object: 'neko.observatory', method: 'status', expect: { '': {} }, reject: true });

function card(title, children) {
	return E('section', { 'class': 'nk-card' }, [ E('h3', {}, [ title ]) ].concat(children));
}

function metric(label, value) {
	return E('div', { 'class': 'nk-metric' }, [ E('span', {}, [ label ]), E('strong', {}, [ value ]) ]);
}

function stateText(state) {
	var states = {
		ok: _('Connected'), disabled: _('AC collection disabled'), pending: _('Waiting for AC'),
		credentials_missing: _('AC credential file is missing'), credentials_permissions: _('AC credential file must be root-owned with mode 600'),
		credentials_invalid: _('AC credential file is invalid'), request_failed: _('AC request failed'),
		auth_expired: _('AC authentication failed'), api_rejected: _('AC rejected the request'),
		invalid_endpoint: _('Invalid AC address'), unavailable: _('Collector unavailable')
	};
	return states[state] || _('AC collection failed');
}

return view.extend({
	handleSave: null, handleSaveApply: null, handleReset: null,
	load: function() {
		return L.resolveDefault(callStatus(), { state: 'unavailable', ac: { state: 'unavailable' }, vlans: [] });
	},
	render: function(data) {
		var self = this;
		if (!document.getElementById('neko-dashboard-css')) document.head.appendChild(E('link', {
			id: 'neko-dashboard-css', rel: 'stylesheet', href: L.resource('neko/dashboard.css')
		}));
		this.root = E('div', { 'class': 'nk-dashboard' });
		this.seconds = 1800;
		this.data = data;
		this.paint();
		poll.add(function() {
			return callStatus().then(function(next) { self.data = next; self.failed = false; self.paint(); }, function() { self.failed = true; self.paint(); });
		}, 5);
		return this.root;
	},
	paint: function() {
		var focused = document.activeElement;
		var focusName = focused && this.root.contains && this.root.contains(focused) ? focused.getAttribute('data-nk-focus') : null;
		var cursor = focusName === 'search' ? focused.selectionStart : null;
		var self = this, data = this.data || {}, ac = data.ac || {}, vlans = data.vlans || [], now = Date.now() / 1000;
		var old = !data.sampled_at || now - data.sampled_at > 20 || this.failed;
		var system = data.system || {};
		var aps = ac.aps || [], clients = ac.clients || [], ssids = ac.ssids || [];
		var apNames = Object.create(null);
		aps.forEach(function(ap) { apNames[ap.mac] = ap.name || ap.mac; });
		var status = E('p', { 'class': old || data.state !== 'ok' ? 'nk-warning' : 'nk-note', role: 'status' }, [
			old ? _('Collector unavailable or stale; showing the last sample.') : _('Last router sample:') + ' ' + obs.stamp(data.sampled_at)
		]);
		if (data.state === 'discovery_failed') status.appendChild(E('span', {}, [ ' · ', _('VLAN discovery failed; interface list may be stale.') ]));
		var select = E('select', { 'data-nk-focus': 'vlan', 'aria-label': _('VLAN chart'), change: function(event) { self.selected = event.target.value; self.paint(); } },
			vlans.map(function(v) { return E('option', { value: v.device, selected: self.selected === v.device }, [ v.label, ' · ', v.device ]); }));
		var selected = vlans.filter(function(v) { return v.device === self.selected; })[0] || vlans[0];
		if (selected) select.value = selected.device;
		var range = E('select', { 'data-nk-focus': 'period', 'aria-label': _('Chart period'), change: function(event) { self.seconds = Number(event.target.value); self.paint(); } },
			[ [300, _('5 minutes')], [1800, _('30 minutes')], [3600, _('60 minutes')] ].map(function(v) { return E('option', { value: v[0], selected: self.seconds === v[0] }, [ v[1] ]); }));
		var acStatus = stateText(ac.state);
		if (ac.collected_at) acStatus += ' · ' + _('Last successful collection:') + ' ' + obs.stamp(ac.collected_at);
		if (ac.stale || ac.state !== 'ok') acStatus += ' · ' + _('Data may be stale; retained records are not live status.');
		var search = this.search || '';
		var searchBox = E('input', { type: 'search', 'data-nk-focus': 'search', value: search, placeholder: _('Search terminals, SSIDs, VLANs or APs'),
			'aria-label': _('Search terminals, SSIDs, VLANs or APs'), input: function(event) { self.search = event.target.value; self.paint(); } });
		var counts = Object.create(null);
		clients.forEach(function(c) { counts[c.mac] = (counts[c.mac] || 0) + 1; });
		var filtered = clients.filter(function(c) { return [c.hostname, c.mac, c.ip, c.ssid, c.vlan, apNames[c.apmac]].join(' ').toLowerCase().indexOf(search.toLowerCase()) >= 0; });
		dom.content(this.root, [
			E('div', { 'class': 'nk-heading' }, [ E('div', {}, [ E('h2', {}, [ _('Network dashboard') ]), status ]),
				E('a', { 'class': 'cbi-button', href: L.url('admin/services/neko-observatory') }, [ _('Collection settings') ]) ]),
			E('div', { 'class': 'nk-summary' }, [
				metric(_('Internal VLANs'), data.sampled_at ? String(vlans.length) : '—'), metric(_('Online APs (AC reported)'), ac.collected_at ? String(aps.filter(function(ap) { return ap.online; }).length) : '—'),
				metric(_('Broadcast SSID / VLAN pairs'), ac.collected_at ? String(ssids.length) : '—'), metric(_('Unique wireless terminals'), ac.unique_clients == null ? '—' : String(ac.unique_clients))
			]),
			card(_('VLAN throughput and traffic'), [
				E('p', { 'class': 'nk-note' }, [ _('Upload = clients → router; download = router → clients. Counters include routed internal traffic, not only Internet traffic. Hardware-switched traffic may bypass these counters.') ]),
				E('div', { 'class': 'nk-vlans' }, vlans.length ? vlans.map(function(v) {
					return E('button', { type: 'button', 'data-nk-focus': 'device:' + v.device, 'class': 'nk-vlan' + (selected && selected.device === v.device ? ' nk-selected' : ''),
						click: function() { self.selected = v.device; self.paint(); } }, [
						E('strong', {}, [ v.label ]), E('small', {}, [ v.device, ' · VLAN ', v.vlan == null ? '—' : String(v.vlan) ]),
						E('span', {}, [ '↑ ', obs.rate(old ? null : v.upload_bps), ' / ↓ ', obs.rate(old ? null : v.download_bps) ]),
						E('small', {}, [ _('Sampled traffic:'), ' ↑ ', obs.bytes(v.upload_bytes), ' / ↓ ', obs.bytes(v.download_bytes) ]),
						E('small', {}, [ _('Since:'), ' ', obs.stamp(v.since), v.state !== 'ok' ? ' · ' + _('Unavailable') : '' ])
					]);
				}) : [ E('p', {}, [ _('No internal VLANs found. Check firewall zones or add logical interfaces in collection settings.') ]) ]),
				E('div', { 'class': 'nk-controls' }, [ select, range ]),
				selected ? obs.chart(selected.history, this.seconds, now) : E('p', {}, [ _('Waiting for interface samples.') ]),
				E('p', { 'class': 'nk-note' }, [ _('Traffic totals cover valid samples since the collector started. Counter resets and missing samples leave chart gaps. History is held in RAM and clears on restart.') ])
			]),
			card(_('GECOOS AC wireless network'), [
				E('p', { 'class': ac.stale || ac.state !== 'ok' ? 'nk-warning' : 'nk-note', role: 'status' }, [ acStatus ]),
				E('p', { 'class': 'nk-note' }, [ _('Wireless data comes from the external AC. Association rows may exceed unique terminals during roaming; AC link rates are not treated as traffic throughput.') ]),
				E('h4', {}, [ _('SSIDs') ]),
				obs.table([_('SSID'), _('VLAN'), _('APs'), _('Bands'), _('Unique terminals')], ssids.map(function(s) { return [s.ssid, s.vlan, s.aps.length, s.bands.join(' / '), s.clients]; })),
				E('h4', {}, [ _('Access points') ]),
				obs.table([_('AP'), _('IP address'), _('Model'), _('Status'), _('Terminals (AC reported)'), _('Last AP report')], aps.map(function(ap) {
					var stale = !ap.reported_at || now - ap.reported_at > (ac.ap_stale_after || 180) || ap.reported_at > now + 60;
					return [ap.name || ap.mac, ap.ip, ap.model, (ap.online ? _('Online') : _('Offline')) + (stale || ac.stale || ac.state !== 'ok' ? ' · ' + _('Stale / unverified') : ''), ap.clients, obs.stamp(ap.reported_at)];
				})),
				E('h4', {}, [ _('Wireless terminals'), ' · ', String(ac.unique_clients == null ? '—' : ac.unique_clients), ' / ', _('Association rows'), ' ', String(ac.associations == null ? '—' : ac.associations) ]),
				searchBox,
				obs.table([_('Terminal'), _('IP address'), _('MAC address'), _('SSID'), _('VLAN'), _('AP'), _('Band'), _('Signal'), _('Association')], filtered.slice(0, 200).map(function(c) {
					return [c.hostname, c.ip, c.mac, c.ssid, c.vlan, apNames[c.apmac] || c.apmac, c.radio, c.signal == null ? '—' : c.signal + ' dBm', counts[c.mac] > 1 ? _('Multiple associations') : '—'];
				})),
				filtered.length > 200 ? E('p', {}, [ _('Showing the first 200 matches; narrow the search to see other terminals.') ]) : null
			]),
			card(_('Router system'), [ E('div', { 'class': 'nk-summary' }, [
				metric(_('Uptime (hours)'), system.uptime == null ? '—' : (system.uptime / 3600).toFixed(1)),
				metric(_('Load average (1 / 5 / 15 min)'), (system.load || []).join(' / ') || '—'),
				metric(_('Available memory'), obs.bytes(system.memory_available)), metric(_('Total memory'), obs.bytes(system.memory_total))
			]) ])
		]);
		// Polling preserves the control and search position being used.
		if (focusName && this.root.querySelectorAll) Array.prototype.forEach.call(this.root.querySelectorAll('[data-nk-focus]'), function(node) {
			if (node.getAttribute('data-nk-focus') !== focusName) return;
			node.focus({ preventScroll: true });
			if (cursor != null && node.setSelectionRange) node.setSelectionRange(cursor, cursor);
		});
	}
});
