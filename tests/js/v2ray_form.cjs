// Execute the actual LuCI form with an in-memory adapter; no RPCs or services run.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,
  '../../local-packages/luci-app-v2ray-server/htdocs/luci-static/resources/view/services/v2ray-server.js'), 'utf8');
const state = {main: {enable: '1', accept_lan: '1'}, fixture: {enable: '0', protocol: 'shadowsocks',
  port: '8443', method: 'aes-256-gcm', password: 'fixture-only', ss_network: 'tcp,udp',
  transport: 'tcp', tcp_guise: 'none', tls: '0'}};
const before = JSON.stringify(state);
let sections;
function Map() { sections = {}; }
Map.prototype.section = function(_type, name) {
  const options = {}; sections[name] = options;
  const add = (_tab, _type, field) => {
    const o = {map: this, choices: [], dependencies: [],
      value(value) { this.choices.push(value); },
      depends(value) { this.dependencies.push(value); },
      formvalue(section) { return state[section]?.[field]; }
    };
    options[field] = o; return o;
  };
  return {tab() {}, option: (type, field) => add('', type, field), taboption: add};
};
Map.prototype.lookupOption = function(name) { return [sections.user[name]]; };
Map.prototype.render = () => sections;
const page = new Function('view', 'form', 'uci', '_', source)(
  {extend: value => value}, {Map}, {load: async () => {}}, text => text);
page.render();
const user = sections.user;
for (const field of Object.values(user)) assert.equal(field.retain, true);
for (const name of ['password','kcp_seed','quic_key']) assert.equal(user[name].password, true);
assert.equal(sections.global.enable.default, '0');
assert.equal(user.enable.default, '0');
assert.equal(user.listen.default, undefined);
assert.deepEqual(user.protocol.choices, ['shadowsocks','vmess','vless','trojan','socks','http']);
assert.deepEqual(user.transport.choices, ['tcp','ws','h2','kcp','quic','grpc']);
assert.equal(user.uuid.datatype, undefined); // The pinned LuCI has no built-in UUID type.
const uuid = '11111111-2222-4333-8444-555555555555';
assert.equal(user.uuid.validate('fixture',uuid),true);
assert.equal(user.uuid.validate('fixture',[uuid,uuid.toUpperCase()]),true);
for (const value of [[],undefined,'bad',[uuid,'bad']]) assert.notEqual(user.uuid.validate('fixture',value),true);
assert.equal(user.level.validate('fixture','255'),true);
assert.notEqual(user.level.validate('fixture','256'),true);
state.fixture.protocol='vmess'; assert.equal(user.level.validate('fixture','256'),true);
state.fixture.protocol='shadowsocks';
for (const name of ['tls_cert','tls_key']) {
  assert.equal(user[name].validate('fixture','/etc/local-material/current'),true);
  for (const value of ['relative','/bad\nline','/bad\0byte','']) assert.notEqual(user[name].validate('fixture',value),true);
}
assert.equal(JSON.stringify(state),before); // Disabled/inactive fields remain untouched.
console.log('PASS: V2Ray form choices, masked controls, inactive values, listener requirements and protocol validation');
