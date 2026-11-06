// Execute the real LuCI form with a small UCI/form adapter. No router is modified.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,
  '../../local-packages/luci-app-socat/htdocs/luci-static/resources/view/services/socat.js'), 'utf8');
let state, options;
const uci = {
  load: async () => {},
  get: (_config, section, field) => state[section]?.[field],
  set: (_config, section, field, value) => { state[section][field] = value; }
};
function Map() { options = {}; }
Map.prototype.section = () => ({ option: (_type, name) => {
  const o = { value() {}, depends() {} }; options[name] = o; return o;
} });
Map.prototype.render = () => options;
const page = new Function('view', 'form', 'uci', '_', source)(
  {extend: value => value}, {Map}, uci, text => text);

state = {forward: {enable: '1', user: 'nobody',
  SocatOptions: '-d -d TCP6-LISTEN:8000,fork TCP4:192.0.2.20:80'}};
page.render();
assert.equal(options.enable.default, '1'); // backend enable:bool:1
assert.equal(options.user.placeholder, 'root'); // backend user:string:root
assert.equal(options._representation.cfgvalue('forward'), 'string');
const original = state.forward.SocatOptions;
options._legacy_options.write('forward', options._legacy_options.cfgvalue('forward'));
options._argument_list.remove('forward');
options._representation.write('forward', 'string');
assert.equal(state.forward.SocatOptions, original);
assert.equal(state.forward.enable, '1');
assert.equal(state.forward.user, 'nobody');
assert(!('_representation' in state.forward));

const argv = ['-d', '-d', 'TCP-LISTEN:8000,fork', 'EXEC:program with spaces'];
options._argument_list.write('forward', argv);
page.render();
assert.equal(options._representation.cfgvalue('forward'), 'list');
assert.deepEqual(options._argument_list.cfgvalue('forward'), argv);
options._legacy_options.remove('forward');
assert.deepEqual(state.forward.SocatOptions, argv);

options._legacy_options.write('forward', original);
assert.equal(options._representation.cfgvalue('forward'), 'string');
assert.equal(state.forward.SocatOptions, original);
assert.deepEqual(Object.keys(state.forward).sort(), ['SocatOptions', 'enable', 'user']);
console.log('PASS: legacy strings, structured argv, and representation changes preserve backend UCI data');
