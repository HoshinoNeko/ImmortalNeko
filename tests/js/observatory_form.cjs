const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '../../local-packages/luci-app-neko-dashboard/htdocs/luci-static/resources');
let options = {};
function Map() {}
Map.prototype.section = () => ({ option(type, name) { return options[name] = {}; } });
Map.prototype.render = () => options;
const page = new Function('view', 'form', '_', fs.readFileSync(path.join(root, 'view/services/neko-observatory.js'), 'utf8'))({extend: x => x}, {Map}, x => x);
page.render();
assert.equal(options.enabled.default, '1');
assert.equal(options.history_points.datatype, 'range(60,720)');
assert.equal(options.ac_password_file.datatype, 'file');
assert.equal(options.ac_url.validate('', 'http://192.0.2.1'), true);
for (const url of ['http://admin:pass@192.0.2.1', 'javascript:bad', 'http://192.0.2.1/api', 'http://192.0.2.1?password=x'])
  assert.equal(typeof options.ac_url.validate('', url), 'string');

function Element(tag, attrs = {}, children = []) { this.tag = tag; this.attrs = attrs; this.children = children.filter(x => x != null); this.listeners = {}; }
Element.prototype.appendChild = function(child) { this.children.push(child); return child; };
Element.prototype.setAttribute = function(name, value) { this.attrs[name] = value; };
Element.prototype.addEventListener = function(name, fn) { this.listeners[name] = fn; };
const E = (tag, attrs, children) => new Element(tag, attrs, children);
const document = {createElementNS: (_ns, tag) => E(tag), getElementById: () => null, head: E('head')};
const obs = new Function('baseclass', 'document', 'E', '_', fs.readFileSync(path.join(root, 'neko/observatory.js'), 'utf8'))({extend:x=>x}, document, E, x=>x);
assert.equal(obs.rate(1250000), '1.25 Mbit/s');
assert.equal(obs.rate(null), '—');
assert.equal(obs.bytes(2048), '2.00 KiB');
const graph = obs.paths([[100, null, null], [105, 1000, 2000], [110, null, null], [115, 0, 0], [160, 1000, 2000]], 100, 160);
assert.equal(graph.max, 2000);
assert.equal(graph.lines[0].length, 3); // Reset/null and a long gap are not joined.
assert(graph.lines[0][2].startsWith('790.0,')); // Time axis, not sample index.
let poll;
const rpc = {declare(spec) { assert.equal(spec.object, 'neko.observatory'); assert.equal(spec.method, 'status'); return async () => ({}); }};
const dashboard = new Function('view', 'rpc', 'poll', 'dom', 'obs', 'L', 'document', 'E', '_', fs.readFileSync(path.join(root, 'view/neko/dashboard.js'), 'utf8'))(
  {extend:x=>x}, rpc, {add:fn=>poll=fn}, {content:(node, children)=>node.children=children}, obs,
  {resource:x=>x, url:x=>x, resolveDefault:(p,v)=>p.catch(()=>v)}, document, E, x=>x);
const hostile = '<img src=x onerror=alert(1)>';
const data = {state:'ok',sampled_at:Date.now()/1000,vlans:[{device:'lan.20',label:hostile,history:[],state:'ok'}],
  ac:{state:'ok',collected_at:100,aps:[{name:hostile,mac:'02:00:5e:00:00:01',online:true,reported_at:1}],
    clients:[{mac:'02:00:5e:00:00:02',ssid:hostile,apmac:'02:00:5e:00:00:01'}],ssids:[],unique_clients:1,associations:1}};
const rendered = dashboard.render(data);
function tags(node) { return typeof node === 'string' ? [] : [node.tag, ...(node.children || []).flatMap(tags)]; }
function strings(node) { return typeof node === 'string' ? [node] : (node.children || []).flatMap(strings); }
assert(strings(rendered).includes(hostile));
assert(!tags(rendered).includes('img')); // E() receives data inside arrays as text.
assert(strings(rendered).some(s=>s.includes('Stale / unverified')));
assert(!strings(rendered).includes('Radios'));
dashboard.failed = true; dashboard.paint();
assert(strings(rendered).includes('Collector unavailable or stale; showing the last sample.'));
assert.equal(typeof poll, 'function');
console.log('PASS: dashboard form, chart units/gaps/time axis, AC replacement, hostile text and stale data');
