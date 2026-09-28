"""Rebuild UI with bundled assets and the existing embedded airport dataset.

Use build_gate_map.py when refreshing the geographic/historical dataset itself.
"""
from pathlib import Path
import json
import re
from airport_geometry import build_geo3d

BASE = Path(__file__).resolve().parent

def render():
    template = (BASE / 'map_template.html').read_text()
    previous = (BASE / 'vhhh_gate_map.html').read_text()
    match = re.search(r'<script id="data" type="application/json">(.*?)</script>', previous, re.S)
    if not match:
        raise ValueError('Missing dataset; run build_gate_map.py first')
    dataset = json.loads(match.group(1))
    dataset['geo3d'] = build_geo3d(dataset['geo'])
    replacements = {'__DATA__': json.dumps(dataset,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')}
    for token, name in [('__LEAFLET_CSS__','leaflet.css'),('__LEAFLET_JS__','leaflet.js'),('__THREE_JS__','three.min.js'),('__ORBIT_JS__','OrbitControls.js')]:
        replacements[token] = (BASE / 'vendor' / name).read_text()
    for token, value in replacements.items():
        if template.count(token) != 1:
            raise ValueError('Template token missing or duplicated: ' + token)
        template = template.replace(token, value)
    target = BASE / 'vhhh_gate_map.html'
    temp = target.with_suffix('.tmp')
    temp.write_text(template)
    temp.replace(target)
    print('Rebuilt vhhh_gate_map.html')

if __name__ == '__main__':
    render()
