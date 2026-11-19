const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const root = path.join(__dirname, '../../local-packages/luci-app-neko-l2vpn/htdocs/luci-static/resources');
const source = fs.readFileSync(path.join(root, 'view/network/neko-l2vpn.js'), 'utf8');
let options;
function option(_type, name, title) {
  const field = { title, choices: [], dependencies: [], value(...v) { this.choices.push(v); }, depends(d) { this.dependencies.push(d); } };
  options[name] = field;
  return field;
}
function Map() { options = {}; }
Map.prototype.section = () => ({option});
Map.prototype.render = () => options;
const page = new Function('view', 'form', 'uci', 'widgets', '_', source)(
  {extend: v => v}, {Map}, {load: async () => {}}, {}, v => v);
page.render();
assert.equal(options.enabled.default, '0');
assert.equal(options.uuid.password, true);
assert.equal(options.uuid.validate('', 'bad'), 'Enter a complete UUID.');
assert.equal(options.uuid.validate('', 'f3dc8467-7d0b-4b1c-9b60-ecce99836729'), true);
assert.equal(options.reality_short_id.validate('', '0011aabb'), true);
assert.equal(typeof options.reality_short_id.validate('', 'abc'), 'string');
assert.deepEqual(options.security.choices.map(v => v[0]), ['tls', 'reality']);
assert(options.egress_device.dependencies.some(d => d.role === 'client'));
assert(options.certificate_file.dependencies.some(d => d.role === 'server' && d.security === 'tls'));
assert(options.reality_private_key_file.dependencies.some(d => d.role === 'server' && d.security === 'reality'));
for (const field of Object.values(options)) assert.equal(field.retain, true);
assert.equal(options.proxy_port.default, '51821');
assert.equal(options.listen_address.default, undefined);
assert.equal(options.uuid.default, undefined);

let protocol;
const network = {registerPatternVirtual() {}, getIfnameOf: v => v,
  registerProtocol(name, value) { assert.equal(name, 'neko_l2tp'); protocol = value; return value; }};
new Function('form', 'network', 'widgets', '_', fs.readFileSync(path.join(root, 'protocol/neko_l2tp.js'), 'utf8'))({}, network, {}, v => v);
options = {};
protocol.sid = 'home'; protocol._ubus = () => null;
protocol.renderFormOptions({taboption: (_tab, ...args) => option(...args)});
assert.equal(protocol.getIfname(), 'nl2-home');
assert.equal(protocol.getPackageName(), 'neko-l2vpn');
assert.equal(protocol.isVirtual(), true);
assert.equal(protocol.containsDevice('nl2-home'), true);
assert.equal(options.tunlink.exclude, 'home');
assert.equal(options.mtu.datatype, 'range(1280,9000)');
assert.equal(options.mtu.default, undefined);
for (const name of ['tunlink', 'ipaddr', 'peeraddr', 'tunnel_id', 'peer_tunnel_id', 'session_id', 'peer_session_id', 'mtu'])
  assert.equal(options[name].rmempty, false);
console.log('PASS: L2 VPN roles, TLS/REALITY field retention, masked UUID, validation and netifd protocol options');
