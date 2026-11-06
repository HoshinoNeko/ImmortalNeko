const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,
  '../../local-packages/luci-app-pptp-server/htdocs/luci-static/resources/view/services/pptp-server.js'), 'utf8');
const state = {pptpd: {enabled: '0', localip: '192.0.2.1', remoteip: '192.0.2.10-20',
  remotedns: '192.0.2.53 198.51.100.53', mppe: ['require-mppe-128']},
  account: {username: 'fixture user', password: 'fixture-only'}};
let sections;
const uci = {load: async () => {}, get: (_config, section, field) => state[section]?.[field]};
function Map() { sections = {}; }
Map.prototype.section = (_type, name, sectionType) => {
  const key = name === 'pptpd' ? sectionType : name;
  sections[key] = {};
  return {option: (_kind, field) => {
    const o = {depends() {}}; sections[key][field] = o; return o;
  }};
};
Map.prototype.render = () => sections;
const page = new Function('view', 'form', 'uci', '_', source)(
  {extend: x => x}, {Map}, uci, x => x);
page.render();
assert.deepEqual(sections.service.remotedns.cfgvalue('pptpd'), ['192.0.2.53','198.51.100.53']);
assert.deepEqual(sections.service.mppe.cfgvalue('pptpd'), ['require-mppe-128']);
for (const field of ['localip','remoteip','remotedns','mppe']) assert.equal(sections.service[field].retain, true);
assert.equal(sections.login.password.password, true);
assert.equal(sections.login.password.validate('account','with spaces "quotes" \\ punctuation'), true);
for (const value of ['bad\nline','bad\rtail','bad\ttab','bad\0nul']) {
  assert.notEqual(sections.login.password.validate('account',value), true);
  assert.notEqual(sections.login.username.validate('account',value), true);
}
// Rendering never rewrites disabled service addresses or existing account values.
assert.equal(state.pptpd.enabled, '0');
assert.equal(state.pptpd.remoteip, '192.0.2.10-20');
assert.equal(state.account.password, 'fixture-only');
console.log('PASS: PPTP fields preserve legacy DNS/MPPE values, retain disabled options and reject control characters');
