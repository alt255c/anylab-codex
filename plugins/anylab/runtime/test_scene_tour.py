"""Presentation copies must preserve operational models and produce supported tours."""
from pathlib import Path
import tempfile,unittest
from scene_tour import prepare_scene_tour
from models import load,child
from conveyor import by_name
from bridge.anylogic import field

class SceneTours(unittest.TestCase):
    def test_all_four_scene_profiles_keep_source_and_initialize_live_camera(self):
        for task in ['4.1','4.2','6.1','6.2']:
            with self.subTest(task=task),tempfile.TemporaryDirectory() as folder:
                source=Path(__file__).parent/f'templates/models/{task}/1/Model.alp'
                original=source.read_bytes()
                _,model=load(source);main=by_name(child(model,'ActiveObjectClasses'),'ActiveObjectClass')['Main']
                startup=field(main,'StartupCode')
                target,_,_,manifest=prepare_scene_tour(source,Path(folder)/'tour',96)
                self.assertEqual(original,source.read_bytes())
                _,copy=load(target);agent=by_name(child(copy,'ActiveObjectClasses'),'ActiveObjectClass')['Main']
                code=field(agent,'StartupCode')
                self.assertIn(startup,code)
                self.assertIn('System.nanoTime()',code)
                self.assertIn('Math.toRadians',code)
                self.assertGreaterEqual(manifest['hold_seconds'],3)
                self.assertGreaterEqual(len(manifest['route']),4)
                self.assertEqual(len(agent.getElementsByTagName('EmbeddedObject')),len(main.getElementsByTagName('EmbeddedObject')))
