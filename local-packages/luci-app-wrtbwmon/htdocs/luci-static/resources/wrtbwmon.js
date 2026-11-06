'use strict';
'require baseclass';

function parseSnapshot(payload) {
	const required = ['family', 'mac', 'ip', 'rx_bytes', 'tx_bytes'];
	if (!payload || !Array.isArray(payload.columns) || !Array.isArray(payload.data))
		throw new Error('Invalid accounting response');
	const index = {};
	for (const name of required) {
		index[name] = payload.columns.indexOf(name);
		if (index[name] < 0 || payload.columns.lastIndexOf(name) !== index[name])
			throw new Error('Missing or duplicate accounting column: ' + name);
	}
	const hosts = new Map();
	for (const record of payload.data) {
		if (!Array.isArray(record))
			throw new Error('Invalid accounting record');
		const family = Number(record[index.family]);
		const mac = String(record[index.mac]).toUpperCase();
		const ip = record[index.ip];
		const rx = record[index.rx_bytes], tx = record[index.tx_bytes];
		if ((family !== 4 && family !== 6) || !/^([0-9A-F]{2}:){5}[0-9A-F]{2}$/.test(mac) ||
		    typeof ip !== 'string' || !ip || /[\s\x00-\x1f\x7f]/.test(ip) ||
		    !Number.isSafeInteger(rx) || !Number.isSafeInteger(tx) || rx < 0 || tx < 0)
			throw new Error('Invalid accounting values');
		// A missing neighbor MAC must not merge unrelated clients into one host.
		const identity = mac === '00:00:00:00:00:00' ? family + ':' + ip : mac;
		const host = hosts.get(identity) || {identity: identity, mac: mac, addresses: [], rx: 0, tx: 0};
		if (!host.addresses.includes(ip)) host.addresses.push(ip);
		host.rx += rx; host.tx += tx;
		if (!Number.isSafeInteger(host.rx) || !Number.isSafeInteger(host.tx))
			throw new Error('Accounting counters exceed safe precision');
		hosts.set(identity, host);
	}
	return Array.from(hosts.values());
}

function createSampler(ratesEnabled) {
	let previous = null;
	return {
		reset: function() { previous = null; },
		sample: function(payload, timestamp) {
			if (!Number.isFinite(timestamp)) throw new Error('Invalid sample timestamp');
			const rows = parseSnapshot(payload);
			const elapsed = previous ? timestamp - previous.timestamp : 0;
			for (const row of rows) {
				const old = previous && previous.hosts.get(row.identity);
				row.rxRate = row.txRate = null;
				if (ratesEnabled !== false && old && elapsed > 0 && row.rx >= old.rx && row.tx >= old.tx) {
					row.rxRate = (row.rx - old.rx) / elapsed;
					row.txRate = (row.tx - old.tx) / elapsed;
				}
			}
			previous = {timestamp: timestamp, hosts: new Map(rows.map(row => [row.identity, row]))};
			return rows;
		}
	};
}

function counterInterval(value) {
	if (value == null || value === '') return 30; // Official daemon init default.
	const match = /^(\d+)([smhdw]?)$/.exec(String(value));
	if (!match) return null;
	const seconds = Number(match[1]) * ({'': 1, s: 1, m: 60, h: 3600, d: 86400, w: 604800}[match[2]]);
	return Number.isSafeInteger(seconds) && seconds > 0 && seconds <= 604800 ? seconds : null;
}

function formatBytes(value) {
	if (value == null || !Number.isFinite(value) || value < 0) return '\u2014';
	const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'];
	let unit = 0;
	while (value >= 1024 && unit < units.length - 1) { value /= 1024; unit++; }
	return (unit ? value.toFixed(2) : Math.round(value).toString()) + ' ' + units[unit];
}

return baseclass.extend({
	parseSnapshot: parseSnapshot,
	createSampler: createSampler,
	counterInterval: counterInterval,
	formatBytes: formatBytes
});
