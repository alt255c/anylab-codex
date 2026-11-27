import csv
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from models import load
from studio_build import MEASUREMENTS, METRO_CAMERA_PROFILE, build, config_from, save_json
from studio_grid import read_grid, resume_grid
from studio_presets import configure_metro_grid


class MetroResume(TestCase):
    def test_studio_build_reports_progress_when_resuming_later_experiment(self):
        with TemporaryDirectory() as tmp:
            root=Path(tmp)
            data=root/"Рабочие файлы"
            data.mkdir()
            config=config_from({"lab":"4","student":"Проверка","group":"QA"})
            save_json(root/"Настройки.json",config)
            source=Path(__file__).parent/"templates/models/4.2/1/Model.alp"
            model=data/"Model.alp"
            model.write_bytes(source.read_bytes())
            exp_41=MEASUREMENTS["4.1"][0][0]
            exp_42=MEASUREMENTS["4.2"][0][0]
            video=data/"demo.mp4"
            video.touch()
            tour=data/"tour.json"
            save_json(tour,{"labels":[]})
            save_json(data/"Готовые этапы.json",{
                "Модели ЛР4 · отделка платформ":{"4.1":str(model),"4.2":str(model)},
                f"4.1 — {exp_41}":"completed.csv",
                "4.1 · запись · "+METRO_CAMERA_PROFILE:{"video":str(video),"tour":str(tour)},
                "4.1 · кадры на остановках · "+METRO_CAMERA_PROFILE:{},
            })
            updates=[]

            def run_grid(path, name, metrics, data, output, run_model, update):
                self.assertEqual(name,exp_42)
                update(6,9,None)
                raise RuntimeError("test reached 4.2")

            with patch("projects.copy_resources"), patch("studio_grid.resume_grid",side_effect=run_grid):
                with self.assertRaisesRegex(RuntimeError,"test reached 4.2"):
                    build(config,root,progress=lambda *args:updates.append(args))

            self.assertIn((f"4.1 — {exp_41}","done"),updates)
            self.assertIn((f"4.2 — {exp_42}","active",6,9,None),updates)

    def test_recovers_legacy_rows_and_runs_only_remaining_slice(self):
        base=Path(__file__).parent/"templates/models/4.2/1/Model.alp"
        experiment,metrics=MEASUREMENTS["4.2"][0]
        with TemporaryDirectory() as tmp:
            data=Path(tmp)
            source=data/"Model.alp"
            doc,model=load(base)
            configure_metro_grid(model,"4.2")
            source.write_bytes(doc.toxml(encoding="utf-8"))
            old=data/"эксперимент-old"/"run"
            old.mkdir(parents=True)
            (old/"result.json").write_text(json.dumps({"model":str(source),"experiment":experiment,
                "sha256":hashlib.sha256(source.read_bytes()).hexdigest(),"state":"timeout"}),encoding="utf-8")

            def metrics_table(file, multipliers):
                with file.open("w",encoding="utf-8",newline="") as stream:
                    writer=csv.writer(stream)
                    writer.writerow(metrics)
                    for multiplier in multipliers:
                        for rate in (150,450,750):
                            writer.writerow([500,500,rate,multiplier,10,2,3,4])

            metrics_table(old/"metrics.csv",(.5,1))
            calls=[]
            def run(staged, folder, name, **kwargs):
                calls.append(read_grid(staged,name,metrics)[2])
                folder.mkdir()
                metrics_table(folder/"metrics.csv",(1.5,))

            updates=[]
            with patch("studio_grid.copy_resources"):
                output=resume_grid(source,experiment,metrics,data,data/"full.csv",run,
                                   lambda count,total,table:updates.append((count,total)))
            self.assertEqual(len(calls),1)
            self.assertEqual(tuple(map(float,calls[0][1][2])),(1.5,))
            self.assertEqual(updates[0],(6,9))
            with open(output,encoding="utf-8") as stream:
                self.assertEqual(len(list(csv.DictReader(stream))),9)
