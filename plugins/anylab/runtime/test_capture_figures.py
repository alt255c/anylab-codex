"""Capture evidence survives crops; fabricated and altered diagrams are rejected."""
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image, ImageDraw
from capture_figures import capture_figure, validate_capture_figure, digest


class CaptureFigures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.raw = self.root / 'raw.png'
        image = Image.new('RGB', (240, 120), 'white')
        ImageDraw.Draw(image).rectangle((25, 20, 90, 70), fill='blue')
        image.save(self.raw)
        self.raw.with_name('raw.png.capture.json').write_text(json.dumps({
            'kind': 'anylogic-window-capture', 'sha256': digest(self.raw),
            'window': {'title': 'Fixture for capture receipt validation'},
        }), encoding='utf8')

    def test_native_crops_and_stacked_panels_preserve_pixels(self):
        target = self.root / 'figure.png'
        capture_figure([{'path': str(self.raw), 'box': [10, 10, 140, 90]},
                        {'path': str(self.raw), 'box': [0, 0, 240, 120]}], target)
        validate_capture_figure(target)
        with Image.open(target) as image:
            self.assertEqual(image.size, (240, 224))
            self.assertEqual(image.getpixel((80, 20)), (0, 0, 255))

    def test_arbitrary_png_is_not_native_capture(self):
        fake = self.root / 'drawn.png'
        Image.new('RGB', (240, 120), 'white').save(fake)
        with self.assertRaisesRegex(ValueError, 'capture'):
            validate_capture_figure(fake)

    def test_changed_source_and_repainted_figure_are_rejected(self):
        target = self.root / 'figure.png'
        capture_figure([{'path': str(self.raw)}], target)
        image = Image.open(target).convert('RGB')
        image.putpixel((0, 0), (255, 0, 0)); image.save(target)
        with self.assertRaisesRegex(ValueError, 'изменена'):
            validate_capture_figure(target)
        # Updating the output hash cannot conceal painted pixels.
        proof = target.with_name(target.name + '.figure.json')
        data = json.loads(proof.read_text(encoding='utf8'));data['sha256'] = digest(target)
        proof.write_text(json.dumps(data), encoding='utf8')
        with self.assertRaisesRegex(ValueError, 'фрагменты'):
            validate_capture_figure(target)
        image.save(self.raw)
        with self.assertRaisesRegex(ValueError, 'Исходный снимок изменён'):
            validate_capture_figure(self.raw)

    def test_invalid_crop_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'box'):
            capture_figure([{'path': str(self.raw), 'box': [-1, 0, 200, 100]}], self.root/'bad.png')

    def test_report_builder_requires_native_logic_figures(self):
        from unittest.mock import patch
        from anylab import finish_lab_report
        guide = json.loads((Path(__file__).parent/'templates/reports/lab-5.fields.json').read_text(encoding='utf8'))
        logic = {key: item for key, item in guide['images'].items() if item['field'].startswith('LOGIC_')}
        self.assertEqual(set(logic), {'5', '9'})
        self.assertTrue(all(v.get('source_kind') == 'anylogic-window-capture' for v in logic.values()))
        (self.root/'lab-plan.json').write_text(json.dumps({
            'report_mode': 'reference', 'student': 'Test', 'group': 'Test', 'report_sha256': 'test'
        }), encoding='utf8')
        (self.root/'reference-fields.json').write_text(json.dumps({
            'paragraphs': [], 'images': [{'id': k} for k in logic],
            'fill_fields': {'paragraphs': {}, 'images': logic}
        }), encoding='utf8')
        fake = self.root/'fake.png'; Image.new('RGB', (240, 120), 'white').save(fake)
        with self.assertRaisesRegex(ValueError, 'LOGIC_1'):
            finish_lab_report(self.root, self.root/'out.docx', {}, {'5': str(fake), '9': str(fake)})
        with patch('materials.check_reuse', return_value=[]), patch('reference_docx.refill_reference', return_value='passed'):
            self.assertEqual(finish_lab_report(self.root, self.root/'out.docx', {},
                             {'5': str(self.raw), '9': str(self.raw)}), 'passed')
