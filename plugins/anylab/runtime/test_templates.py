"""Integrity checks for the publicly distributable course templates."""
import json,re,unittest,zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT=Path(__file__).parent/"templates"
CATALOG=json.loads((ROOT/"templates.json").read_text(encoding="utf8"))

def entries():
    for lab,bundle in CATALOG.items():
        for task,models in bundle["models"].items():
            for model in models:yield lab,task,model

class TemplateIntegrity(unittest.TestCase):
    def test_every_task_has_standalone_model_and_fields(self):
        self.assertEqual(set(CATALOG),set(map(str,range(1,7))))
        rows=list(entries());self.assertEqual(len(rows),15)
        for lab,task,entry in rows:
            with self.subTest(task=task):
                self.assertEqual(entry["kind"],"alp")
                model=ROOT/entry["file"];ET.parse(model)
                self.assertTrue((ROOT/entry["fields"]).is_file())
                allowed=entry.get("required_install_resources",[])
                for resource in ET.parse(model).findall("./Model/ModelResources/Resource"):
                    if resource.findtext("Location","FILE_SYSTEM")!="FILE_SYSTEM":continue
                    name=resource.findtext("Path")
                    if name:self.assertTrue((model.parent/name).is_file() or name in allowed,name)

    def test_no_student_identity_in_public_models_or_reports(self):
        pattern=re.compile(r"Игнатов|Солдаткин|Ignatov|Soldatkin|Б24.?503|dv-te",re.I)
        for _,task,entry in entries():
            self.assertIsNone(pattern.search((ROOT/entry["file"]).read_text(encoding="utf8")),task)
        for lab,bundle in CATALOG.items():
            with zipfile.ZipFile(ROOT/bundle["report"]) as archive:
                for name in archive.namelist():
                    if name.endswith(".xml"):
                        self.assertIsNone(pattern.search(archive.read(name).decode("utf8")),f"{lab}:{name}")

    def test_report_markers_have_fill_fields_and_common_labs_have_no_variant(self):
        for lab,bundle in CATALOG.items():
            report=ROOT/bundle["report"]
            with zipfile.ZipFile(report) as archive:
                xml=ET.fromstring(archive.read("word/document.xml"))
                text="".join(xml.itertext());markers=set(re.findall(r"{{([A-Z0-9_]+)}}",text))
            guide=json.loads(report.with_suffix(".fill.json").read_text(encoding="utf8")) if report.with_suffix(".fill.json").is_file() else None
            if guide:declared=set(guide.get("text",{}))|set(guide.get("images",{}))|set(guide.get("tables",{}))
            else:
                guide=json.loads(report.with_suffix(".fields.json").read_text(encoding="utf8"))
                declared={field for section in ("paragraphs","images") for v in guide[section].values() for field in re.findall(r"[A-Z][A-Z0-9_]*",v.get("field",""))}
            self.assertFalse(markers-declared,(lab,markers-declared))
            if int(lab)>=4:self.assertNotIn("VARIANT",markers)

    def test_gas_payment_returns_each_driver_to_own_car(self):
        entry=CATALOG["6"]["models"]["6.2"][0]
        xml=(ROOT/entry["file"]).read_text(encoding="utf8")
        self.assertTrue("ожиданиеВодителя.stopDelay(agent.car)" in xml)
        for name in ("очередьКассы1","очередьКассы2","оплатаКасса1","оплатаКасса2","возвратВодителя","returnedDrivers","RoadNetworkDescriptor"):
            self.assertIn(name,xml)
        root=ET.fromstring(xml)
        for counter in root.findall('.//Rectangle'):
            if counter.findtext('Name','') in ('Касса1','Касса2'):
                self.assertLessEqual(float(counter.findtext('ZHeight')),12)
        cars=[n for n in root.findall('.//ActiveObjectClass') if n.findtext('Name')=='Car']
        self.assertEqual(len(cars),1)
        figures={n.findtext('Name'):n for n in cars[0].findall('.//Figure3D')}
        self.assertEqual(figures['car'].findtext('VisibleCode'),'false')
        colors=[]
        for fuel in ['GAS95','GAS92','DIESEL']:
            figure=figures['carFuel'+fuel]
            self.assertEqual(figure.findtext('VisibleCode'),'fuelType==FuelType.'+fuel)
            colors.append(next(n.findtext('Color') for n in figure.findall('.//ColorMapping') if n.findtext('Name')=='Material__4__Surf'))
        self.assertEqual(len(set(colors)),3)
        self.assertNotIn("refreshCargo",xml)

    def test_compact_geometry_and_palette_change_the_actual_project(self):
        from projects import installation
        if installation() is None:self.skipTest("AnyLogic installation required")
        import tempfile
        from scenarios import conveyor_scenario
        from models import load,child,children,field,anchors
        source=ROOT/CATALOG["5"]["models"]["5.2"][0]["file"]
        with tempfile.TemporaryDirectory() as folder:
            result=conveyor_scenario(source,Path(folder)/"compact",8,600,73,True,
                "orange_cream_blue","compact_straight","orange_sleeve")
            _,model=load(result["model"])
            belt=next(n for n in model.getElementsByTagName("Conveyor") if field(n,"Name")=="loadingBelt")
            self.assertEqual(anchors(belt)[-1][0],110)
            carton=next(n for n in children(child(model,"ActiveObjectClasses"),"ActiveObjectClass") if field(n,"Name")=="Carton")
            shape=next(n for n in carton.getElementsByTagName("Rectangle") if field(n,"Name")=="carton2D")
            self.assertEqual(int(field(shape,"FillColor"))&0xffffff,0xE88448)
            fragile=next(n for n in carton.getElementsByTagName("Rectangle") if field(n,"Name")=="fragile_carton2D")
            self.assertEqual(int(field(fragile,"FillColor"))&0xffffff,0x9B4A8C)

if __name__=="__main__":unittest.main()
