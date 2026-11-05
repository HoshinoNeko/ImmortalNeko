"""Assemble fragments and reject silently dropped Kconfig selections."""
import json
from scripts.fwlib import ROOT, assert_config, config_values, requested_config, run

def configure(src, p, work):
    wanted = requested_config(p, work)
    text = ''.join(k+'='+v+'\n' for k,v in sorted(wanted.items()))
    (src/'.config').write_text(text)
    (work/'requested.config').write_text(text)
    run(['make', 'defconfig'], src)
    assert_config(wanted, config_values((src/'.config').read_text()))
    (work/'profile.json').write_text(json.dumps(p, indent=2)+'\n')
