import json
import tempfile
import unittest
from pathlib import Path
from video_plan import load_plan


class VideoPlan(unittest.TestCase):
    def test_narrow_fix_preserves_route_and_timing_without_plan(self):
        with tempfile.TemporaryDirectory() as folder:
            route=[[1,2,3,35,-45],[3,4,5,35,-45]];timing={'holds':[8,8]}
            self.assertEqual(load_plan(Path(folder)/'m.alp',route,timing,30),(route,timing,None))

    def test_agreed_stops_and_holds_cover_entire_recording(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'video-plan.json'
            plan=dict(camera_route=[[1,2,3,35,-45]]*3,hold_seconds=[12,16,18],transition_seconds=2,two_d_seconds=10)
            path.write_text(json.dumps(plan),encoding='utf8')
            route,timing,_=load_plan(path.with_name('m.alp'),[],{},60)
            self.assertEqual(timing['starts'],[10,24,42])
            self.assertEqual(timing['starts'][-1]+timing['holds'][-1],60)
            plan['hold_seconds']=[4,16,26];path.write_text(json.dumps(plan),encoding='utf8')
            with self.assertRaises(ValueError):load_plan(path.with_name('m.alp'),[],{},60)
