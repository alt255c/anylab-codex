"""Regressions for invisible feeder travel and destructive template reuse."""
import unittest
import json
import re
import tempfile
from pathlib import Path

from bridge.anylogic import field, put
from conveyor import by_name, repair_loading_flow, validate_loading_flow
from cargo import apply_cargo,validate_cargo
from models import child, children, load


class LoadingRegression(unittest.TestCase):
    def models(self):
        return Path(__file__).parent.glob("templates/models/5.*/*/*.alp")

    def main(self, model):
        return by_name(child(model,"ActiveObjectClasses"),"ActiveObjectClass")["Main"]

    def test_both_templates_have_real_travel(self):
        paths=list(self.models())
        self.assertEqual(len(paths),2)
        for path in paths:
            with self.subTest(model=path.name):
                _,model=load(path)
                self.assertTrue(validate_loading_flow(self.main(model))["physical_loading"])

    def test_rejects_old_invisible_offset(self):
        _,model=load(next(self.models()))
        main=self.main(model)
        feeder=next(n for n in main.getElementsByTagName("Conveyor") if field(n,"Name")=="partFeeder")
        positions=by_name(child(feeder,"Presentation"),"PositionOnConveyor")
        put(positions["partStart"],"Offset","450")
        with self.assertRaisesRegex(ValueError,"смещения|partStart"):
            validate_loading_flow(main)

    def test_repair_does_not_duplicate_flow_or_counters(self):
        for path in self.models():
            with self.subTest(model=path.name):
                doc,model=load(path)
                main=self.main(model)
                repair_loading_flow(doc,model,main)
                apply_cargo(doc,model,main)
                before={tag:len(main.getElementsByTagName(tag)) for tag in ("EmbeddedObject","Connector","Variable","PositionOnConveyor")}
                repair_loading_flow(doc,model,main)
                apply_cargo(doc,model,main)
                after={tag:len(main.getElementsByTagName(tag)) for tag in before}
                self.assertEqual(before,after)
                self.assertTrue(validate_loading_flow(main)["physical_loading"])
                gate=by_name(child(main,"EmbeddedObjects"),"EmbeddedObject")["loadingGate"]
                self.assertIsNotNone(gate)

    def test_native_cargo_has_exclusive_open_and_closed_states(self):
        for path in self.models():
            doc,model=load(path)
            carton=by_name(child(model,"ActiveObjectClasses"),"ActiveObjectClass")["Carton"]
            shapes=by_name(child(carton,"Presentation/Level/Presentation"),"Rectangle")
            def visible(name,role,sealed,manual=False,fragile=False,ready=True):
                expression=field(shapes[name],"VisibleCode").replace("&&"," and ").replace("||"," or ")
                expression=re.sub(r"!(?!=)"," not ",expression).strip()
                return eval(expression,{"__builtins__":{}},dict(cargoReady=ready,cargoRole=role,isSealed=sealed,isManuallyAdded=manual,isFragile=fragile,hasPalletSheet=True,hasAssemblyPart=role==3))
            for role in (0,1,2,3,4):
                for sealed in (False,True):
                    for manual in (False,True):
                        for fragile in (False,True):
                            self.assertEqual(sum(visible(prefix+"closedLid",role,sealed,manual,fragile) for prefix in ("","fragile_","manual_")),int(role==3 and sealed))
                            self.assertEqual(sum(visible(prefix+"flapfront",role,sealed,manual,fragile) for prefix in ("","fragile_","manual_")),int(role==3 and not sealed))
                            self.assertEqual(sum(visible(prefix+"carton2D",role,sealed,manual,fragile) for prefix in ("","fragile_","manual_")),int(role==3))
            self.assertFalse(visible("carton2D",3,False,ready=False))
            self.assertFalse(carton.getElementsByTagName("Figure3D"),"Cargo must not share cached mesh materials")
            self.assertEqual(float(field(shapes["manual_boxfloor"],"Z")),0)
            self.assertEqual(float(field(shapes["manual_closedLid"],"Z")),18)
            self.assertFalse(carton.getElementsByTagName("FillColorCode"),"Category bodies must use static colors")
            for name,color in [("boxfront","#19B6B0"),("fragile_boxfront","#F28A3C"),("manual_boxfront","#2457CC")]:
                from conveyor import argb
                self.assertEqual(int(field(shapes[name],"FillColor")),argb(color))
                self.assertEqual(field(shapes[name],"FillColor"),field(shapes[name],"LineColor"))

    def test_manual_lane_waits_clear_of_main_and_stock_is_replenished(self):
        from models import anchors
        for path in self.models():
            _,model=load(path);main=self.main(model)
            belts={field(n,"Name"):n for n in main.getElementsByTagName("Conveyor")}
            lane=belts["manualFeeder"]
            positions={field(n,"Name"):n for n in main.getElementsByTagName("PositionOnConveyor")}
            self.assertAlmostEqual(float(field(lane,"X")),float(field(belts["conveyor"],"X"))+float(field(positions["placingPoint"],"Offset"))-100/6)
            self.assertAlmostEqual(float(field(lane,"Y"))+float(field(positions["manualJoin"],"Offset"))-100/6,float(field(belts["conveyor"],"Y"))-50)
            travel=by_name(child(main,"EmbeddedObjects"),"EmbeddedObject")["manualTravel"]
            self.assertNotIn("cargoReady=false",field(child(by_name(child(travel,"Parameters"),"Parameter")["onExit"],"Value"),"Code"))

            blocks=by_name(child(main,"EmbeddedObjects"),"EmbeddedObject")
            if '5.2' in str(path):
                self.assertIn("stockPallets.inject(6)",field(main,"StartupCode"))
                self.assertIn("stockPallets.inject(1)",field(child(by_name(child(blocks["fitPallet"],"Parameters"),"Parameter")["onExit"],"Value"),"Code"))
                self.assertIn('sheetTravel',blocks)
            else:
                self.assertNotIn('stockPallets',blocks)
                self.assertNotIn('sheetSource',blocks)
                self.assertNotIn('loadingBelt',belts)
            self.assertEqual(field(child(by_name(child(blocks['source1'],'Parameters'),'Parameter')['arrivalType'],'Value'),'Code'),'self.MANUAL')



    def test_forklifts_keep_seated_drivers_and_original_visibility(self):
        path=Path(__file__).parent/"templates/models/5.2/1/ConveyorLine.alp"
        _,model=load(path)
        forklift=by_name(child(model,"ActiveObjectClasses"),"ActiveObjectClass")["Forklift"]
        driver=next(n for n in forklift.getElementsByTagName("Figure3D") if field(n,"Name")=="sittingWorker")
        self.assertEqual(field(driver,"DrawMode"),"SHAPE_DRAW_2D3D")
        self.assertEqual(field(child(driver,"ResourceReference"),"ClassName"),"3d/sittingworker.dae")
        self.assertTrue((path.parent/"3d/sittingworker.dae").is_file())
        self.assertNotIn("false",field(driver,"VisibleCode"))



class VideoRegression(unittest.TestCase):
    def test_recording_copy_keeps_operational_startup(self):
        from unittest.mock import patch
        from video_demo import record_tour,tour_timing
        source=Path(__file__).parent/"templates/models/5.2/1/ConveyorLine.alp"
        _,model=load(source)
        original=field(by_name(child(model,"ActiveObjectClasses"),"ActiveObjectClass")["Main"],"StartupCode")
        def inspect_prepared(model,*args,**kwargs):
            _,prepared=load(model)
            main=by_name(child(prepared,"ActiveObjectClasses"),"ActiveObjectClass")["Main"]
            startup=field(main,"StartupCode")
            self.assertIn(original,startup)
            self.assertIn("stockPallets.inject(6);",startup)
            raise RuntimeError("inspection complete")
        with tempfile.TemporaryDirectory() as folder:
            with patch("anylab.run_model",side_effect=inspect_prepared):
                with self.assertRaisesRegex(RuntimeError,"inspection complete"):
                    record_tour(source,Path(folder)/"recording")
        timing=tour_timing(96)
        self.assertEqual(len(timing["holds"]),6)
        self.assertAlmostEqual(timing["starts"][-1]+timing["holds"][-1],96)
        timing=tour_timing(96,True)
        self.assertEqual(len(timing["holds"]),7)
        self.assertAlmostEqual(timing["starts"][-1]+timing["holds"][-1],96)


class ReportRegression(unittest.TestCase):
    def test_embedded_placeholders_are_declared(self):
        from reference_docx import inspect_reference
        root=Path(__file__).parent/"templates/reports/lab-5"
        mapping=json.loads(root.with_suffix(".fields.json").read_text(encoding="utf-8"))["paragraphs"]
        for paragraph in inspect_reference(root.with_suffix(".docx"))["paragraphs"]:
            if re.search(r"\{\{[^{}]+\}\}",paragraph["text"]):
                self.assertIn(paragraph["id"],mapping,paragraph["text"])

    def test_final_report_cannot_keep_unfilled_year(self):
        from docx import Document
        from reference_docx import inspect_reference,refill_reference
        with tempfile.TemporaryDirectory() as folder:
            template=Path(folder)/"template.docx"
            doc=Document();doc.add_paragraph("Москва — {{YEAR}}");doc.save(template)
            layout=inspect_reference(template)
            with self.assertRaisesRegex(ValueError,"незаполненные"):
                refill_reference(template,Path(folder)/"report.docx",{
                    "sha256":layout["sha256"],"paragraphs":{},"images":{},
                    "keep_paragraphs":[layout["paragraphs"][0]["id"]],"keep_images":[]})


if __name__ == "__main__":
    unittest.main()
