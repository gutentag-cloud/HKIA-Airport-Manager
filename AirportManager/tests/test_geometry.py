import sys
from pathlib import Path
import unittest
from shapely.geometry import Polygon
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from airport_geometry import build_geo3d

class GeometryTests(unittest.TestCase):
    def test_small_terminal_keeps_footprint(self):
        ring=[[113.93001,22.31001],[113.93101,22.31001],[113.93101,22.31031],[113.93001,22.31031],[113.93001,22.31001]]
        geo={'features':[{'properties':{'k':'terminal','h':18},'geometry':{'type':'Polygon','coordinates':[ring]}}]}
        built=build_geo3d(geo)['buildings'][0]
        self.assertAlmostEqual(Polygon(built['pts']).area,Polygon(ring).area,places=12)
        self.assertEqual(built['h'],18)
        self.assertGreater(len(set(tuple(p) for p in built['pts'])),3)
    def test_ground_contains_airport_runway(self):
        from shapely.geometry import Point
        line=[[113.90,22.31],[113.94,22.33]]
        geo={'features':[{'properties':{'k':'runway'},'geometry':{'type':'LineString','coordinates':line}}, {'properties':{'k':'runway'},'geometry':{'type':'LineString','coordinates':[[113.90,22.30],[113.94,22.32]]}}]}
        ground=Polygon(build_geo3d(geo)['ground'])
        self.assertTrue(all(ground.covers(Point(p)) for p in line))
        self.assertLess(ground.bounds[2]-ground.bounds[0],.05)

    def test_taxiway_contract(self):
        pts=[[113.93,22.31],[113.931,22.312]]
        geo={'features':[{'properties':{'k':'taxiway','ref':'A'},'geometry':{'type':'LineString','coordinates':pts}}]}
        self.assertEqual(build_geo3d(geo)['twy'],[{'pts':pts,'ref':'A'}])

if __name__=='__main__':unittest.main()
