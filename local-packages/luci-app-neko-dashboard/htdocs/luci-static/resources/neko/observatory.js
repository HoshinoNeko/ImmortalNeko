'use strict';
'require baseclass';

function rate(value) {
	if (typeof value !== 'number' || !isFinite(value)) return '—';
	var units = [ 'bit/s', 'kbit/s', 'Mbit/s', 'Gbit/s' ], n = 0;
	while (value >= 1000 && n < units.length - 1) { value /= 1000; n++; }
	return value.toFixed(n ? 2 : 0) + ' ' + units[n];
}

function bytes(value) {
	if (typeof value !== 'number' || !isFinite(value)) return '—';
	var units = [ 'B', 'KiB', 'MiB', 'GiB', 'TiB' ], n = 0;
	while (value >= 1024 && n < units.length - 1) { value /= 1024; n++; }
	return value.toFixed(n ? 2 : 0) + ' ' + units[n];
}

function stamp(value) {
	return value ? new Date(value * 1000).toLocaleString() : '—';
}

function paths(history, start, end) {
	var rows = history.filter(function(p) { return p[0] >= start && p[0] <= end; });
	var max = 1;
	rows.forEach(function(p) { [ p[1], p[2] ].forEach(function(v) { if (typeof v === 'number' && isFinite(v)) max = Math.max(max, v); }); });
	var lines = [ [], [] ];
	[ 1, 2 ].forEach(function(column, index) {
		var line = [];
		rows.forEach(function(p, i) {
			var v = p[column];
			if (typeof v !== 'number' || !isFinite(v) || (i && p[0] - rows[i - 1][0] > 30)) {
				if (line.length) lines[index].push(line.join(' '));
				line = [];
			}
			if (typeof v === 'number' && isFinite(v)) line.push(((p[0] - start) / Math.max(1, end - start) * 780 + 10).toFixed(1) + ',' + (190 - Math.max(0, v) / max * 170).toFixed(1));
		});
		if (line.length) lines[index].push(line.join(' '));
	});
	return { lines: lines, max: max, rows: rows };
}

function svg(tag, attrs) {
	var node = document.createElementNS('http://www.w3.org/2000/svg', tag);
	Object.keys(attrs).forEach(function(key) { node.setAttribute(key, attrs[key]); });
	return node;
}

function chart(history, seconds, now) {
	var data = paths(history || [], now - seconds, now);
	var graph = svg('svg', { viewBox: '0 0 800 210', role: 'img', 'aria-label': _('Upload and download throughput') });
	graph.appendChild(svg('path', { d: 'M10 20V190H790M10 105H790', 'class': 'nk-axis' }));
	data.lines.forEach(function(lines, i) {
		lines.forEach(function(points) { graph.appendChild(svg('polyline', { points: points, 'class': i ? 'nk-down' : 'nk-up' })); });
	});
	var tip = E('output', { 'class': 'nk-chart-tip', 'aria-live': 'polite' }, [ _('Move over the chart for values.') ]);
	graph.addEventListener('pointermove', function(event) {
		var box = graph.getBoundingClientRect();
		var at = now - seconds + Math.max(0, Math.min(1, (event.clientX - box.left) / box.width)) * seconds;
		var row = data.rows.reduce(function(best, p) { return !best || Math.abs(p[0] - at) < Math.abs(best[0] - at) ? p : best; }, null);
		if (row) tip.textContent = stamp(row[0]) + ' · ↑ ' + rate(row[1]) + ' · ↓ ' + rate(row[2]);
	});
	return E('div', { 'class': 'nk-chart' }, [
		E('div', { 'class': 'nk-chart-labels' }, [ E('span', {}, [ rate(data.max) ]), E('span', {}, [ _('Upload'), ' ↑ / ', _('Download'), ' ↓' ]) ]),
		graph,
		E('div', { 'class': 'nk-chart-labels' }, [ E('span', {}, [ stamp(now - seconds) ]), E('span', {}, [ stamp(now) ]) ]), tip
	]);
}

function table(headers, rows, empty) {
	return E('div', { 'class': 'nk-scroll' }, [ E('table', { 'class': 'table nk-table' }, [
		E('thead', {}, [ E('tr', {}, headers.map(function(h) { return E('th', {}, [ h ]); })) ]),
		E('tbody', {}, rows.length ? rows.map(function(row) { return E('tr', {}, row.map(function(cell) { return E('td', {}, [ cell == null || cell === '' ? '—' : String(cell) ]); })); }) :
			[ E('tr', {}, [ E('td', { colspan: headers.length }, [ empty || _('No records reported.') ]) ]) ])
	]) ]);
}

return baseclass.extend({ rate: rate, bytes: bytes, stamp: stamp, paths: paths, chart: chart, table: table });
