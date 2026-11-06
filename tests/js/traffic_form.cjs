// Exercise actual LuCI accounting logic and its read-only view. No real RPCs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '../../local-packages/luci-app-wrtbwmon');
const source = name => fs.readFileSync(path.join(root, 'htdocs/luci-static/resources', name), 'utf8');
const accounting = new Function('baseclass', source('wrtbwmon.js'))({extend: value => value});
const columns = ['family', 'mac', 'ip', 'rx_bytes', 'tx_bytes'];
const mac = '02:AA:BB:CC:DD:01';
const payload = data => ({columns, data});
const initial = payload([[4, mac, '192.0.2.2', 1000, 100], [6, mac, '2001:db8::2', 2000, 200],
  [4, '00:00:00:00:00:00', '192.0.2.3', 50, 10], [4, '00:00:00:00:00:00', '192.0.2.4', 70, 20]]);
const parsed = accounting.parseSnapshot(initial);
assert.equal(parsed.length, 3);
assert.equal(parsed[0].rx, 3000); assert.equal(parsed[0].tx, 300);
assert.deepEqual(parsed[0].addresses, ['192.0.2.2', '2001:db8::2']);
// The pinned nlbwmon client includes connection/packet columns even when grouped.
const wireFormat = {columns: ['family', 'mac', 'ip', 'conns', 'rx_bytes', 'rx_pkts', 'tx_bytes', 'tx_pkts'],
  data: [[4, mac, '192.0.2.2', 7, 2000, 20, 3000, 30]]};
assert.equal(accounting.parseSnapshot(wireFormat)[0].rx, 2000);
assert.equal(accounting.parseSnapshot(wireFormat)[0].tx, 3000);
const reordered = {columns: ['tx_bytes', 'ip', 'mac', 'rx_bytes', 'family'],
  data: [[100, '192.0.2.2', mac.toLowerCase(), 1000, 4]]};
assert.equal(accounting.parseSnapshot(reordered)[0].tx, 100);
for (const bad of [null, {}, {columns, data: [null]}, {columns: columns.slice(1), data: []},
  {columns: [...columns, 'mac'], data: []}, payload([[4, 'bad-mac', '192.0.2.2', 1, 2]]),
  payload([[4, mac, '192.0.2.2', -1, 2]]), payload([[4, mac, '192.0.2.2', '100', 2]]),
  payload([[4, mac, '192.0.2.2', Number.MAX_SAFE_INTEGER + 1, 2]]),
  payload([[4, mac, '192.0.2.2', Number.MAX_SAFE_INTEGER, 2], [6, mac, '2001:db8::2', 1, 2]])])
  assert.throws(() => accounting.parseSnapshot(bad));
const sampler = accounting.createSampler();
assert.equal(sampler.sample(initial, 10)[0].rxRate, null);
const later = payload([[4, mac, '192.0.2.2', 6000, 600], [6, mac, '2001:db8::2', 2000, 200]]);
let row = sampler.sample(later, 20)[0];
assert.equal(row.rxRate, 500); assert.equal(row.txRate, 50);
// A new accounting period, daemon reset, lost client, clock reversal and read gap
// must never turn old totals into a speed spike or a negative rate.
assert.equal(sampler.sample(initial, 30)[0].rxRate, null);
assert.equal(sampler.sample(initial, 30)[0].rxRate, null);
assert.equal(sampler.sample(initial, 29)[0].rxRate, null);
sampler.sample(payload([]), 40);
assert.equal(sampler.sample(initial, 50)[0].rxRate, null);
sampler.reset(); assert.equal(sampler.sample(later, 60)[0].rxRate, null);
const disabled = accounting.createSampler(false);
disabled.sample(initial, 1); assert.equal(disabled.sample(later, 2)[0].rxRate, null);
assert.equal(accounting.formatBytes(null), '\u2014');
assert.equal(accounting.formatBytes(0), '0 B');
assert.equal(accounting.formatBytes(1536), '1.50 KiB');
for (const [input, expected] of [[undefined, 30], ['30s', 30], ['5m', 300], ['1h', 3600],
  ['5', 5], ['1w', 604800], ['0s', null], ['1m30s', null], ['999999999d', null], ['garbage', null]])
  assert.equal(accounting.counterInterval(input), expected);

(async () => {
  let current = initial, failure = false, clock = 10000, calls = 0, tableRows;
  const polls = [];
  const acl = JSON.parse(fs.readFileSync(path.join(root, 'root/usr/share/rpcd/acl.d/luci-app-wrtbwmon.json')));
  const allowed = acl['luci-app-wrtbwmon'];
  assert.equal(allowed.write, undefined);
  const backend = {exec_direct: async (command, args, type) => {
    calls++;
    assert.equal(type, 'json');
    assert.deepEqual(allowed.read.file[[command, ...args].join(' ')], ['exec']);
    assert.deepEqual(allowed.read['cgi-io'], ['exec']);
    if (failure) throw new Error('offline');
    return current;
  }};
  const E = (tag, attrs = {}, children = []) => ({tag, attrs, children,
    value: attrs.value || (tag === 'select' ? children[0].attrs.value : ''), textContent: ''});
  const L = {resolveDefault: (p, fallback) => p.catch(() => fallback), url: p => '/cgi-bin/luci/' + p};
  const network = {getHostHints: async () => ({getHostnameByMACAddr: value => value === mac ? '<untrusted-hostname>' : ''})};
  const uci = {load: async name => { assert.equal(name, 'nlbwmon'); }, get_first: () => '30s'};
  const page = new Function('view', 'fs', 'network', 'poll', 'uci', 'accounting', 'L', '_', 'E',
    'cbi_update_table', 'performance', source('view/network/traffic-status.js'))(
      {extend: value => value}, backend, network, {add: (fn, interval) => polls.push({fn, interval})},
      uci, accounting, L, text => text, E, (_table, rows) => { tableRows = rows; }, {now: () => clock});
  page.render(await page.load());
  assert.equal(calls, 1); assert.equal(polls[0].interval, 30);
  assert.equal(tableRows[0][0].children, '<untrusted-hostname>'); // passed as a text child, not HTML
  assert.equal(tableRows[0][5], '\u2014');
  page.filter.value = '2001:db8'; page.filter.attrs.input(); assert.equal(tableRows.length, 1);
  assert.equal(calls, 1); // filters and sorting never invoke RPCs or mutate configuration
  current = later; clock += 30000; await polls[0].fn();
  assert.equal(tableRows[0][5], '167 B/s');
  failure = true; await polls[0].fn();
  assert(page.status.textContent.includes('unavailable'));
  assert.equal(tableRows[0][5], '\u2014');
  failure = false; clock += 30000; await polls[0].fn();
  assert.equal(tableRows[0][5], '\u2014');
  assert.equal(page.handleSaveApply, null);
  assert.equal(page.handleSave, null);
  console.log('PASS: traffic grouping, sampled rates, resets, filtering, view errors and read-only RPC ACL');
})().catch(error => { console.error(error); process.exitCode = 1; });
