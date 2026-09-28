"""Prepare airport geometry in longitude/latitude degrees, preserving metre-scale detail."""
from shapely.geometry import Polygon, MultiPoint
from shapely.ops import unary_union


def build_geo3d(geo):
    aprons, buildings, runways, taxiways = [], [], [], []
    for feature in geo['features']:
        props, shape = feature['properties'], feature['geometry']
        kind, coords = props['k'], shape['coordinates']
        if kind == 'runway' and shape['type'] == 'LineString':
            runways.append(coords)
        elif kind == 'taxiway' and shape['type'] == 'LineString':
            taxiways.append({'pts': coords, 'ref': props.get('ref', '')})
        elif shape['type'] == 'Polygon' and kind in ('apron','building','terminal','hangar','construction'):
            polygon = Polygon(coords[0], coords[1:]).buffer(0)
            if polygon.is_empty:
                continue
            parts = list(polygon.geoms) if polygon.geom_type == 'MultiPolygon' else [polygon]
            for part in parts:
                if kind == 'apron':
                    aprons.append(part)
                else:
                    # ~1 metre in geographic degrees, not 1 degree (~111 km).
                    ring = part.simplify(.00001, preserve_topology=True).exterior
                    buildings.append({'pts': [[round(x,6),round(y,6)] for x,y in ring.coords],
                                      'h': max(6.,min(140.,float(props.get('h') or 10))), 'k':kind})
    apron_rings = []
    if aprons:
        merged = unary_union(aprons).simplify(.00001, preserve_topology=True)
        parts = list(merged.geoms) if merged.geom_type == 'MultiPolygon' else [merged]
        apron_rings = [[[round(x,6),round(y,6)] for x,y in part.exterior.coords] for part in parts]
    footprint = [p for line in runways for p in line]+[p for ring in apron_rings for p in ring]+[p for b in buildings if b['k']=='terminal' for p in b['pts']]
    ground = [[round(x,6),round(y,6)] for x,y in MultiPoint(footprint).convex_hull.buffer(.0007).exterior.coords] if len(footprint)>2 else []
    return {'ground':ground,'aprons':apron_rings,'buildings':buildings,'rwy':runways,'twy':taxiways}
