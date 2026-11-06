// Actual LuCI form with in-memory UCI/DOM adapters; no services or sysctls run.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname,
  '../../local-packages/luci-app-turboacc/htdocs/luci-static/resources/view/network/turboacc.js'), 'utf8');
async function exercise(features) {
  const state = {turboacc: {legacy: {bbr_cca:'1',sw_flow:'1',hw_flow:'1',fullcone_nat:'2',dns_caching:'0'}},
    firewall: {defaults: {flow_offloading:'0',flow_offloading_hw:'0',fullcone:'2'}},
    dnsproxy: {global:{enabled:'0'},servers:{upstream:[]},cache:{enabled:'0'}}};
  const before = JSON.stringify(state), maps = {}, writes = [], reads = [];
  function Map(name) { this.name=name; this.sections={}; maps[name]=this; }
  Map.prototype.section = function(_type,name) {
    const options={}; this.sections[name]=options;
    return {option: (_kind,field) => {
      const o={map:this, choices:[], value(v) { this.choices.push(v); },
        formvalue(section) { return state[this.map.name]?.[section]?.[field]; }};
      options[field]=o; return o;
    }};
  };
  Map.prototype.lookupOption = function(name,section) { return [this.sections[section]?.[name]]; };
  Map.prototype.render = function() { return Promise.resolve(this.name); };
  const uci={load:async () => {},get:(config,section,key) => state[config]?.[section]?.[key],
    set:(config,section,key,value) => { writes.push([config,section,key,value]); state[config][section][key]=value; }};
  const L={resolveDefault:(p,fallback) => p.catch(() => fallback),hasSystemFeature:()=>features,
    toArray:v => Array.isArray(v) ? v : v == null ? [] : [v]};
  const page = new Function('view','form','uci','fs','L','_','E',source)(
    {extend:v=>v},{Map},uci,{read:async name=>{reads.push(name);return name.includes('available') ? 'reno cubic bbr\n' : 'cubic\n';}},
    L,v=>v,(tag,attrs,nodes)=>({tag,attrs,nodes}));
  const nodes=await page.render(await page.load());
  assert.deepEqual(nodes.nodes,['turboacc','firewall','dnsproxy']);
  assert.equal(JSON.stringify(state),before); assert.deepEqual(writes,[]);
  assert.deepEqual(reads,['/proc/sys/net/ipv4/tcp_congestion_control','/proc/sys/net/ipv4/tcp_available_congestion_control']);
  const bbr=maps.turboacc.sections.turboacc, fw=maps.firewall.sections.defaults;
  assert.equal(bbr._current.cfgvalue(),'cubic');
  assert.equal(bbr._available.cfgvalue(),'reno cubic bbr'); assert.equal(bbr.bbr_cca.default,'0');
  assert.match(bbr._legacy.cfgvalue('legacy'),/FullCone mode: 2/);
  assert.equal(fw._current_flow.cfgvalue('defaults'),'0 / 0');
  assert.equal(fw._current_fullcone.cfgvalue('defaults'),'2');
  if (features) {
    for (const field of ['_set_flow','_set_fullcone']) {
      assert.equal(fw[field].cfgvalue(),'keep'); fw[field].write('defaults','keep'); fw[field].remove('defaults');
    }
    assert.deepEqual(writes,[]); assert.equal(JSON.stringify(state),before);
    for (const [choice,expected] of [['0',['0','0']],['1',['1','0']],['2',['1','1']]]) {
      fw._set_flow.write('defaults',choice);
      assert.deepEqual(writes.slice(-2),[['firewall','defaults','flow_offloading',expected[0]],['firewall','defaults','flow_offloading_hw',expected[1]]]);
    }
    for (const choice of ['0','1']) { fw._set_fullcone.write('defaults',choice); assert.equal(state.firewall.defaults.fullcone,choice); }
    const size=writes.length;
    assert.throws(()=>fw._set_fullcone.write('defaults','2'));
    assert.throws(()=>fw._set_flow.write('defaults','invalid')); assert.equal(writes.length,size);
    assert.equal(state.turboacc.legacy.fullcone_nat,'2');
  } else { assert.equal(fw._set_flow,undefined); assert.equal(fw._set_fullcone,undefined); }
  const dns=maps.dnsproxy.sections;
  assert.equal(dns.global.enabled.default,'0'); assert.equal(dns.cache.enabled.default,'0');
  assert.equal(dns.global.enabled.validate('global','0'),true);
  for (const upstream of [[],['  '],undefined]) {
    state.dnsproxy.servers.upstream=upstream;
    assert.notEqual(dns.global.enabled.validate('global','1'),true);
  }
  state.dnsproxy.servers.upstream=['https://fixture.invalid/dns-query'];
  assert.equal(dns.global.enabled.validate('global','1'),true);
  assert.ok(writes.every(row=>row[0]==='firewall'));
}
(async()=>{await exercise(true);await exercise(false);
  console.log('PASS: Turbo ACC explicit firewall choices, legacy preservation, read-only state and DNS upstream validation');
})().catch(error=>{console.error(error);process.exitCode=1;});
