'use strict';
'require view';
'require fs';
'require network';
'require poll';
'require uci';
'require wrtbwmon as accounting';

function readCounters() {
	return fs.exec_direct('/usr/libexec/nlbwmon-action',
		['download', '-g', 'family,mac,ip', '-o', '-rx_bytes,-tx_bytes'], 'json');
}

return view.extend({
	load: function() {
		return Promise.all([
			readCounters().then(data => ({data: data}), error => ({error: error})),
			L.resolveDefault(network.getHostHints(), null),
			uci.load('nlbwmon')
		]);
	},

	accept: function(data) {
		this.rows = this.sampler.sample(data, performance.now() / 1000);
		this.status.textContent = _('Last sample:') + ' ' + new Date().toLocaleTimeString();
		this.drawRows();
	},

	reportError: function() {
		this.sampler.reset();
		for (const row of this.rows) row.rxRate = row.txRate = null;
		this.status.textContent = _('Traffic data unavailable. Start nlbwmon after configuring its monitored networks. Displayed totals are from the last successful sample.');
		this.drawRows();
	},

	refresh: function() {
		return readCounters().then(data => this.accept(data)).catch(() => this.reportError());
	},

	drawRows: function() {
		const filter = this.filter.value.trim().toLowerCase();
		const sort = this.sort.value;
		const score = row => sort === 'download' ? row.rx : sort === 'upload' ? row.tx :
			sort === 'rate' ? (row.rxRate || 0) + (row.txRate || 0) : row.rx + row.tx;
		const rows = this.rows.map(row => ({...row, hostname: this.hints ?
			(this.hints.getHostnameByMACAddr(row.mac) || '') : ''})).filter(row =>
			[row.hostname, row.mac, ...row.addresses].join(' ').toLowerCase().includes(filter));
		rows.sort((a, b) => score(b) - score(a) || a.identity.localeCompare(b.identity));
		const rate = value => value == null ? '\u2014' : accounting.formatBytes(value) + '/s';
		cbi_update_table(this.table, rows.map(row => [
			E('span', {}, row.hostname || row.mac),
			E('span', {}, row.mac),
			E('span', {}, row.addresses.join(', ')),
			accounting.formatBytes(row.rx), accounting.formatBytes(row.tx),
			rate(row.rxRate), rate(row.txRate)
		]), E('em', _('No matching traffic data.')));
	},

	render: function(data) {
		this.hints = data[1];
		this.rows = [];
		const interval = accounting.counterInterval(uci.get_first('nlbwmon', 'nlbwmon', 'refresh_interval'));
		this.sampler = accounting.createSampler(interval !== null);
		this.status = E('p', {'role': 'status', 'aria-live': 'polite'});
		this.filter = E('input', {type: 'search', 'class': 'cbi-input-text',
			placeholder: _('Hostname, MAC or IP address'),
			'aria-label': _('Filter devices'), input: () => this.drawRows()});
		this.sort = E('select', {'class': 'cbi-input-select', 'aria-label': _('Sort by'),
			change: () => this.drawRows()}, [
			E('option', {value: 'total'}, _('Total traffic')),
			E('option', {value: 'download'}, _('Download traffic')),
			E('option', {value: 'upload'}, _('Upload traffic')),
			E('option', {value: 'rate'}, _('Sampled rate'))
		]);
		this.table = E('table', {'class': 'table cbi-section-table'}, [
			E('tr', {'class': 'tr table-titles'}, [
				_('Device'), _('MAC address'), _('IPv4 / IPv6 addresses'),
				_('Downloaded'), _('Uploaded'), _('Download rate'), _('Upload rate')
			].map(title => E('th', {'class': 'th'}, title)))
		]);
		try {
			if (data[0].error) throw data[0].error;
			this.accept(data[0].data);
		} catch (error) { this.reportError(); }
		// Poll no faster than the daemon updates counters, avoiding artificial bursts.
		poll.add(() => this.refresh(), Math.max(5, interval || 30));
		return E('div', {'class': 'cbi-map'}, [
			E('h2', {}, _('Per-device traffic')),
			E('p', {}, _('Totals cover the active nlbwmon accounting period. Rates use differences between samples; counter refresh follows the daemon interval, so these are sampled averages. The first sample, failed reads and decreasing counters have no rate.')),
			E('p', {}, [E('a', {href: L.url('admin/services/nlbw/config')}, _('Accounting settings')),
				' \u00b7 ', E('a', {href: L.url('admin/services/nlbw/backup')}, _('Database backup'))]),
			E('div', {'class': 'cbi-value'}, [this.filter, ' ', this.sort]),
			this.status, this.table
		]);
	},

	handleSave: null,
	handleSaveApply: null,
	handleReset: null
});
