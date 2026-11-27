"""Run an AnyLab Studio recipe and retain the evidence for human review."""
import csv
import base64
from io import BytesIO
from datetime import date
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import time
import zipfile

from studio_presets import LABS, make_models

STATION_CAMERA_PROFILE = "station_following_full_plan"
METRO_CAMERA_PROFILE = "metro_station_layouts_clear_tracks"
BOARDING = {"Посадка · путь 1":"pedSink1.countPeds()", "Посадка · путь 2":"pedSink2.countPeds()"}
DEMO_SPEEDS = (0.5, 1, 2, 3, 4)

METRO = {"Очередь к турникетам 1": "MaxОчередьТурникетВходSide1",
         "Очередь к турникетам 2": "MaxОчередьТурникетВходSide2",
         "Очередь к кассе 1": "MaxОчередьКассаSide1", "Очередь к кассе 2": "MaxОчередьКассаSide2"}
CONVEYOR = {"Интенсивность": "ИнтенсивностьПрибытия", "Основной вход": "source.count()",
            "Хрупкие на входе": "fragileEntered", "Упаковано хрупких": "packedFragile"}
STATION = {"Спрос": "интенсивностьПрибытия", "Правило": "правилоОчереди", "Повтор": "номерПовтора",
           "Въехали": "arrived", "Обслужено": "served", "Объезд": "завершилиОбъезд"}
MEASUREMENTS = {
    "4.1": [("ВарьированиеИнтенсивностиВход", {"Интенсивность": "ИнтенсивностьВход", **METRO, **BOARDING})],
    "4.2": [(name, {"Вход в метро": "ИнтенсивностьВход", "Выход из метро": "ИнтенсивностьВыход",
                    "Вход с улицы": "ИнтенсивностьУлица", "Множитель": "МножительОбслуживания",
                    "Посещения ТЦ": "mallCompleted", "Среднее время в ТЦ": "mallMeanTime", **BOARDING})
            for name in ("ВарьированиеВремявТЦ", "ВлияниеПотокаМетроНаТц")],
    "5.1": [("Capacity", {**CONVEYOR, "Обработано": "sink.count()"})],
    "5.2": [("Capacity", {**CONVEYOR, "Обычные доставлены": "ordinaryDelivered",
                         "Хрупкие доставлены": "fragileDelivered", "Ручные доставлены": "manualDelivered"})],
    "6.1": [("АнализИнтенсивности", STATION)],
    "6.2": [("АнализИнтенсивности", {**STATION, "Оплатили": "paid", "Вернулись": "returnedDrivers"})],
}
DESCRIPTIONS = {
    "4.1": "Измерены максимальные очереди двух вестибюлей при изменении входного потока.",
    "4.2": "Проверены измерения посещений торгового центра при изменении потока и времени обслуживания.",
    "5.1": "Оценена работа среднего участка с основным потоком и отдельной ручной подачей.",
    "5.2": "Оценена работа полной линии с подготовкой поддонов и разгрузкой коробок.",
    "6.1": "На модели АЗС с четырьмя колонками измерен выпуск при разных уровнях спроса.",
    "6.2": "В эксперименте дополнительно измерены оплаты и возвраты водителей к своим машинам.",
}


def variants_for(lab):
    import anylab
    choices=[set(task["available_variants"]) for task in anylab.task_data(int(lab),"")
             if task["available_variants"]]
    return sorted(set.intersection(*choices),key=int) if choices else []


def config_from(raw):
    if not isinstance(raw, dict):
        raise ValueError("Ожидается объект настроек")
    lab = str(raw.get("lab", ""))
    if lab not in LABS:
        raise ValueError("Выберите лабораторную от 1 до 6")
    preset = LABS[lab]
    config = {"lab": lab}
    for item, limit in {"student": 80, "group": 30, "teacher": 80, "variant": 8,
                        "station": 70, "sign": 50, "notes": 4000, "idea": 4000}.items():
        value = raw.get(item, "")
        if not isinstance(value, str) or len(value)>limit or any(ord(c)<32 and (item not in {"notes","idea"} or c not in "\r\n\t") for c in value):
            raise ValueError(f"Проверьте поле {item}")
        config[item] = value.strip()
    if not config["student"] or not config["group"]:
        raise ValueError("Укажите студента и группу")
    valid_variants=variants_for(lab)
    if valid_variants and config["variant"] not in valid_variants:
        raise ValueError("Выберите вариант из списка")
    if not valid_variants:
        config["variant"]=""
    template = raw.get("template", next(iter(preset["templates"]),""))
    if not isinstance(template,str) or template not in (preset["templates"] or {""}):
        raise ValueError("Шаблон отсутствует в каталоге")
    addons = raw.get("addons", [])
    if not isinstance(addons, list) or any(not isinstance(a,str) or a not in preset["addons"] for a in addons):
        raise ValueError("Выберите дополнения из каталога")
    config.update(template=template,addons=list(dict.fromkeys(addons)))
    for name, choices in preset.get("choices",{}).items():
        value = raw.get(name,next(iter(choices)))
        if not isinstance(value,str) or value not in choices:
            raise ValueError("Недействительный выбор в каталоге")
        config[name]=value
    seed=raw.get("seed",73)
    if type(seed) is not int or not 0<=seed<=2147483647:
        raise ValueError("Зерно должно быть целым числом от 0 до 2147483647")
    config["seed"]=seed
    colors=raw.get("colors",{})
    palettes={"4":{"metro_walls","metro_accent","mall_floor","mall_facade"},
              "5":{"ordinary","fragile","manual","sheet","tape","rollers"},
              "6":{"station_roof","station_walls","station_trim"}}
    if not isinstance(colors,dict) or set(colors)-palettes.get(lab,set()) or any(
        not isinstance(value,str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}",value) for value in colors.values()
    ):
        raise ValueError("Цвета должны быть в формате #RRGGBB")
    config["colors"]=colors
    hold=raw.get("hold",0)
    if type(hold) is not int or (hold and not 5<=hold<=12):
        raise ValueError("Остановки камеры — от 5 до 12 секунд")
    config["hold"]=hold
    speed=raw.get("speed",0)
    if type(speed) not in (int,float) or speed not in (0,*DEMO_SPEEDS):
        raise ValueError("Выберите скорость демонстрации из списка")
    config["speed"]=speed
    photo=raw.get("photo","")
    if not isinstance(photo,str) or len(photo)>2_800_000:
        raise ValueError("Фото должно быть PNG или JPEG размером до 2 МБ")
    config["photo"]=photo
    if photo:
        photo_image(photo)
    return config


def photo_image(encoded):
    from PIL import Image
    try:
        raw=base64.b64decode(encoded,validate=True)
        with Image.open(BytesIO(raw)) as image:
            if image.format not in {"PNG","JPEG"} or len(raw)>2_097_152 or image.width*image.height>20_000_000:
                raise ValueError("Неподдерживаемое фото")
            result=image.convert("RGB")
            result.thumbnail((1600,1200))
            return result
    except (OSError,ValueError) as error:
        raise ValueError("Фото должно быть PNG или JPEG размером до 2 МБ") from error


def camera_plan(model_path, part, hold):
    from models import load,child
    from conveyor import by_name
    from scene_tour import route_for
    if not hold:
        return 96 if part.startswith("5") else 64
    if part.startswith("5"):
        count=7 if part=="5.2" else 6
        labels=[]
    else:
        _,model=load(model_path)
        main=by_name(child(model,"ActiveObjectClasses"),"ActiveObjectClass")["Main"]
        _,route,labels=route_for(main)
        count=len(route)
    seconds=12+count*hold+3*(count-1)
    save_json(Path(model_path).parent/"video-plan.json",
              {"hold_seconds":[hold]*count,"two_d_seconds":12,"transition_seconds":3,"stop_labels":labels})
    return seconds


def catalog():
    return {lab:{**preset,"variants":variants_for(lab)} for lab,preset in LABS.items()}


def save_json(path, data):
    tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    for attempt in range(5):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            if attempt==4:
                raise
            time.sleep(.025*(attempt+1))


def preview_frame_times(tour, phase_log=None):
    first=tour.get("two_d_seconds",tour.get("2d_seconds"))
    starts=tour.get("station_start_seconds")
    holds=tour.get("station_hold_seconds",tour.get("hold_seconds"))
    if starts is None:
        starts=[first+sum(holds[:i])+tour["transition_seconds"]*i for i in range(len(holds))]
    if isinstance(holds,list) and len(holds)==len(starts):
        # AnyLogic can still be rendering the preceding view just after a stop.
        # Take the frame late in the hold, before camera movement resumes.
        times=[start+hold*.8 for start,hold in zip(starts,holds)]
    else:
        boundaries=[]
        if phase_log is not None and phase_log.is_file():
            boundaries=[float(row.split(";",3)[2]) for row in phase_log.read_text(encoding="utf-8").splitlines()]
        times=[]
        for start in starts:
            end=next((boundary for boundary in boundaries if boundary>start+.001),start+2)
            times.append(start+min(1.25,(end-start)*.65))
    return [("План",max(1,first/2)),*((f"Ракурс {i+1}",t) for i,t in enumerate(times))]


def capture_frames(video, manifest, folder):
    from imageio_ffmpeg import get_ffmpeg_exe
    manifest=Path(manifest)
    tour=json.loads(manifest.read_text(encoding="utf-8"))
    frames = {}
    for label, timestamp in preview_frame_times(tour,manifest.with_name("tour-events.csv")):
        output=folder/(label+".png")
        pending=output.with_suffix(".tmp.png")
        pending.unlink(missing_ok=True)
        try:
            subprocess.run([get_ffmpeg_exe(),"-hide_banner","-loglevel","error","-y","-ss",str(timestamp),"-i",str(video),
                            "-frames:v","1",str(pending)],check=True,timeout=45)
            if not pending.is_file():
                raise RuntimeError(f"Не извлечён кадр {label} на {timestamp:.1f} с")
            pending.replace(output)
        finally:
            pending.unlink(missing_ok=True)
        frames[label]=str(output)
    return frames


def create_report(config, measurements, captures, directory, text):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Cm, Pt
    from pdf_export import export_pdf
    from PIL import Image
    document=Document()
    section=document.sections[0]
    section.top_margin=section.bottom_margin=Cm(2)
    style=document.styles["Normal"]
    style.font.name="Times New Roman"
    style.font.size=Pt(11)
    document.add_heading(f"Лабораторная работа № {config['lab']}",0)
    document.add_heading(LABS[config["lab"]]["title"],1)
    document.add_paragraph(f"{config['student']} · группа {config['group']} · {date.today().year}")
    if config["teacher"]:
        document.add_paragraph("Преподаватель "+config["teacher"])
    if config["variant"]:
        document.add_paragraph("Вариант "+config["variant"])
    if config["notes"]:
        document.add_heading("Примечания",2)
        document.add_paragraph(config["notes"])
    document.add_heading("Цель работы",2)
    document.add_paragraph(text["goal"])
    def picture(path, label):
        with Image.open(path) as im:
            w,h=im.size
        p=document.add_paragraph()
        p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.keep_with_next=True
        p.add_run().add_picture(str(path),width=Cm(min(15,8*w/h)))
        document.add_paragraph(label,style="Caption")
    if config["photo"]:
        photo=directory/"Проверка"/"Фото пользователя.jpg"
        photo_image(config["photo"]).save(photo,quality=88)
        picture(photo,"Дополнительное фото пользователя")
    for part, sheets in measurements.items():
        document.add_page_break()
        document.add_heading("Задание "+part,1)
        document.add_paragraph(text["parts"][part]["method"])
        for name,path in sheets.items():
            document.add_heading(name,2)
            with Path(path).open(encoding="utf-8-sig",newline="") as stream:
                header,*rows=csv.reader(stream)
            table=document.add_table(rows=1,cols=len(header),style="Table Grid")
            for cell,value in zip(table.rows[0].cells,header):
                cell.text=value
            for row in rows:
                for cell,value in zip(table.add_row().cells,row):
                    cell.text=f"{float(value):.4g}" if value else "—"
            document.add_paragraph(f"Завершённые прогоны — {len(rows)}.")
        document.add_heading("Результаты",2)
        document.add_paragraph(text["parts"][part]["findings"])
        if part=="5.2":
            document.add_paragraph("Обычные заказы идут по основной ветви. Хрупкие помечены знаком бокала. Ручные поступают с отдельного входа и отмечены буквой «Р».")
            picture(directory/"Проверка"/"Состояния коробок.png","Схема состояний груза по цветам модели")
        for label in ("План","Ракурс 1","Ракурс 2"):
            picture(captures[part][label],f"{part} · {label}")
    document.add_heading("Вывод",1)
    document.add_paragraph(text["conclusion"])
    path=directory/"Отчёт.docx"
    document.save(path)
    pdf=directory/"Отчёт.pdf"
    export_pdf(path,pdf)


def validate_archive(package, tasks, lab):
    """Check the delivery contract before publishing a completed ZIP."""
    entries = [item for item in package.infolist() if not item.is_dir()]
    paths = {PurePosixPath(item.filename): item for item in entries}
    if len(paths) != len(entries):
        raise ValueError("В ZIP есть повторяющиеся пути")
    for report in ("Отчёт.docx", "Отчёт.pdf"):
        item = paths.get(PurePosixPath(report))
        if not item or item.file_size == 0:
            raise ValueError(f"В ZIP отсутствует {report}")
    expected_models = set()
    expected_videos = set()
    for task in tasks:
        prefix = PurePosixPath(task)
        models = {path for path in paths if path.parent == prefix and path.suffix.lower() == ".alp"}
        if len(models) != 1:
            raise ValueError(f"{task} · в архиве нужен один ALP")
        expected_models.update(models)
        if lab >= 4:
            expected_videos.add(prefix / "Демонстрация.mp4")
            if not any(path.is_relative_to(prefix / "3d") and paths[path].file_size for path in paths):
                raise ValueError(f"{task} · в архиве отсутствуют 3D-ресурсы")
    for suffix, wanted in ((".alp", expected_models), (".mp4", expected_videos)):
        actual = {path for path in paths if path.suffix.lower() == suffix}
        if actual != wanted or any(paths[path].file_size == 0 for path in actual):
            raise ValueError(f"Проверьте количество и расположение файлов {suffix} в ZIP")
    if package.testzip() is not None:
        raise RuntimeError("ZIP не прошёл проверку целостности")


def publish_archive(content, archive, lab):
    content=content.resolve()
    tmp=archive.with_suffix(".tmp")
    paths=[content/"Отчёт.docx",content/"Отчёт.pdf"]
    tasks=LABS[lab]["tasks"]
    for section in ["Проверка",*tasks]:
        paths.extend(path for path in (content/section).rglob("*") if path.is_file())
    try:
        with zipfile.ZipFile(tmp,"w",zipfile.ZIP_DEFLATED) as package:
            for path in paths:
                if not path.resolve().is_relative_to(content):
                    raise ValueError(f"Файл вне каталога комплекта: {path.name}")
                package.write(path,path.relative_to(content).as_posix(),
                              compress_type=zipfile.ZIP_STORED if path.suffix==".mp4" else None)
        with zipfile.ZipFile(tmp) as package:
            validate_archive(package,tasks,int(lab))
        tmp.replace(archive)
    finally:
        tmp.unlink(missing_ok=True)


def build(raw, destination, note=lambda message: None, *, prepare_only=False, preview_only=False,
          preview_part=None):
    import anylab
    import shutil
    from projects import copy_atomic, copy_resources
    config=config_from(raw)
    root=Path(destination).resolve()
    root.mkdir(parents=True,exist_ok=True)
    plan=root/"Настройки.json"
    if plan.is_file():
        previous=json.loads(plan.read_text(encoding="utf-8"))
        previous.setdefault("speed",0)
        previous.setdefault("idea","")
        if config["lab"]=="4":
            previous.setdefault("metro_station","generic")
            previous.setdefault("mall","atrium")
        if previous!=config:
            raise ValueError("Выберите новый каталог для другой конфигурации")
    elif any(path!=plan.with_suffix(".tmp") for path in root.iterdir()):
        raise ValueError("Укажите новый или пустой каталог")
    else:
        save_json(plan,config)
    data=root/"Рабочие файлы"
    data.mkdir(exist_ok=True)
    completed_path=data/"Готовые этапы.json"
    checkpoints=json.loads(completed_path.read_text(encoding="utf-8")) if completed_path.is_file() else {}

    def once(name, fn):
        if name not in checkpoints:
            checkpoints[name]=fn()
            save_json(completed_path,checkpoints)
        return checkpoints[name]

    if int(config["lab"])<=3:
        if prepare_only or preview_only:
            raise ValueError("ЛР1–3 собираются целиком через Codex")
        from studio_codex import do_early_lab
        from docx import Document

        def early():
            target,models=do_early_lab(config,data/"Задание Codex",LABS[config["lab"]]["tasks"],note)
            Document(target/"Отчёт.docx")
            with (target/"Отчёт.pdf").open("rb") as pdf:
                if pdf.read(5)!=b"%PDF-":
                    raise ValueError("Codex вернул некорректный PDF")
            publish_archive(target,root/"Комплект.zip",config["lab"])
            return models

        models=once("Комплект Codex",early)
        return {"state":"complete","archive":str(root/"Комплект.zip"),"models":models,"photos":{}}

    def prepare():
        import tempfile
        attempt=Path(tempfile.mkdtemp(prefix="модели-",dir=data))
        return make_models(config,attempt,note)

    model_key="Модели ЛР4 · отделка платформ" if config["lab"]=="4" else "Модели"
    old_metro_keys={"Модели","Модели ЛР4 с посадкой","Модели ЛР4 · планировки станций","Модели ЛР4 · стены вестибюлей"}
    if model_key not in checkpoints and config["lab"]=="4" and old_metro_keys.intersection(checkpoints):
        checkpoints={key:value for key,value in checkpoints.items()
                     if key!="Модели после Codex" and key!="Текст отчёта Codex" and not key.startswith(("4.1 ·","4.2 ·","4.1 —","4.2 —"))}
    models=once(model_key,prepare)
    if config["idea"]:
        from studio_codex import customize_models
        models=once("Модели после Codex",lambda:customize_models(config,models,data/"Доработка Codex",note))
    if prepare_only:
        return {"state":"prepared","models":models}
    evidence=root/"Проверка"
    evidence.mkdir(exist_ok=True)
    measurements, captures, shot_labels = {}, {}, {}
    for part,path in models.items():
        if preview_only and preview_part and part!=preview_part:
            continue
        if part.startswith("6"):
            from models import load,child
            from conveyor import by_name
            from station_layout import fix_station_layout
            project=Path(path)
            doc,model=load(project)
            before=doc.toxml(encoding="utf-8")
            main=by_name(child(model,"ActiveObjectClasses"),"ActiveObjectClass")["Main"]
            fix_station_layout(doc,model,main)
            updated=doc.toxml(encoding="utf-8")
            if updated!=before:
                project.write_bytes(updated)
                for name,_ in MEASUREMENTS[part]:
                    checkpoints.pop(f"{part} — {name}",None)
                save_json(completed_path,checkpoints)

        if part.startswith("4") and not any(f"{part} — {name}" in checkpoints for name,_ in MEASUREMENTS[part]):
            from models import load
            from studio_presets import configure_metro_grid
            doc,model=load(path)
            configure_metro_grid(model,part)
            Path(path).write_bytes(doc.toxml(encoding="utf-8"))

        def measure():
            import tempfile
            result={}
            for experiment,metrics in MEASUREMENTS[part]:
                entry=f"{part} — {experiment}"
                def run():
                    note(f"{part} · эксперимент {experiment}")
                    directory=Path(tempfile.mkdtemp(prefix="эксперимент-",dir=data))
                    run_folder=directory/"run"
                    timeout={"4.1":540,"4.2":900}.get(part,240)
                    try:
                        result=anylab.run_model(path,run_folder,experiment,timeout=timeout,close=True,metrics=metrics)
                    except RuntimeError as error:
                        details=run_folder/"result.json"
                        if not details.is_file():
                            raise
                        state=json.loads(details.read_text(encoding="utf-8"))
                        progress=run_folder/"metrics.csv"
                        count=0
                        if progress.is_file():
                            with progress.open(encoding="utf-8-sig",newline="") as stream:
                                count=sum(1 for _ in csv.DictReader(stream))
                        reason="Истекло время ожидания" if state["state"]=="timeout" else state.get("error",state["state"])
                        raise RuntimeError(f"{part} · {experiment}. {reason}. Завершено прогонов: {count}.") from error
                    if not result["finished"]:
                        raise RuntimeError(f"{part} · эксперимент не завершён: {directory}")
                    table=Path(result["metrics_csv"])
                    with table.open(encoding="utf-8-sig",newline="") as stream:
                        rows=list(csv.DictReader(stream))
                    if not rows:
                        raise RuntimeError(f"{part} · эксперимент без измерений: {directory}")
                    if part.startswith("5") and not any(float(row["Упаковано хрупких"])>0 for row in rows):
                        raise RuntimeError(f"{part} · упаковка хрупких не подтверждена: {directory}")
                    copy=evidence/(entry+".csv")
                    shutil.copyfile(table,copy)
                    return str(copy)
                result[experiment]=once(entry,run)
            return result

        def record():
            import tempfile
            note(f"{part} · запись и кадры")
            def video():
                directory=Path(tempfile.mkdtemp(prefix="запись-",dir=data))
                conveyor=part.startswith("5")
                seconds=camera_plan(path,part,config["hold"])
                return anylab.video(path,directory/"run",seconds=seconds,
                                    warmup=15 if conveyor else 8,speed=config["speed"] or None,tour=True,profile="hd")
            schema=" · "+profile if profile else ""
            return once(part+" · MP4"+schema,video)

        if not preview_only:
            measurements[part]=measure()
        profile={"4":METRO_CAMERA_PROFILE,"5":"conveyor_full_plan","6":STATION_CAMERA_PROFILE}[part[0]]
        capture=once(part+" · запись"+(" · "+profile if profile else ""),record)
        frames=evidence/part
        frames.mkdir(exist_ok=True)
        captures[part]=once(part+" · кадры на остановках · "+profile,
                            lambda:capture_frames(capture["video"],capture["tour"],frames))
        tour=json.loads(Path(capture["tour"]).read_text(encoding="utf-8"))
        shot_labels[part]=tour.get("labels",[])
        folder=root/part
        folder.mkdir(exist_ok=True)
        shipped=folder/Path(path).name
        if not shipped.exists() or part.startswith(("4","6")):
            copy_resources(Path(path),folder,False)
            copy_atomic(path,shipped)
        if not (folder/"Демонстрация.mp4").exists() or profile:
            copy_atomic(capture["video"],folder/"Демонстрация.mp4")
        shutil.copyfile(capture["tour"],evidence/(part+" — камера.json"))
    if preview_only:
        return {"state":"preview","models":models,"photos":captures,"shot_labels":shot_labels,
                "camera_profile":profile or "tour"}
    if config["lab"]=="5":
        cargo_chart(models["5.2"],evidence/"Состояния коробок.png")
    note("Отчёт и проверка ZIP")
    if not (root/"Отчёт.pdf").exists() or not (root/"Отчёт.docx").exists():
        from studio_codex import compose_report
        text=once("Текст отчёта Codex",lambda:compose_report(config,measurements,DESCRIPTIONS,data/"Отчёт Codex",note))
        create_report(config,measurements,captures,root,text)
    archive=root/"Комплект.zip"
    save_json(evidence/"Параметры сборки.json",{k:v for k,v in config.items() if k!="photo"})
    publish_archive(root,archive,config["lab"])
    return {"state":"complete","archive":str(archive),"shot_labels":shot_labels,
            "camera_profile":profile or "tour",
            "models":{key:str(root/key/Path(path).name) for key,path in models.items()},"photos":captures}


def cargo_chart(model_path, out):
    """Draw a schematic from the actual cargo palette of the built model."""
    from PIL import Image, ImageDraw, ImageFont
    from models import child, load
    from conveyor import by_name
    from bridge.anylogic import field
    _,model=load(model_path)
    cargo=by_name(child(model,"ActiveObjectClasses"),"ActiveObjectClass")["Carton"]
    presentation=child(cargo,"Presentation/Level/Presentation")
    shapes=by_name(presentation,"Rectangle")

    def tint(name):
        return "#%06x" % (int(field(shapes[name],"FillColor")) & 0xffffff)

    image=Image.new("RGB",(1200,650),"#f2f6f5")
    draw=ImageDraw.Draw(image)
    font=ImageFont.truetype("arial.ttf",22)
    from models import children
    part_shapes=[n for n in children(presentation)
                 if field(n,"DrawMode")=="SHAPE_DRAW_2D"
                 and field(n,"Name").startswith(("component","coffee_","cat_","bore2D"))]

    def draw_part(cx,cy,scale):
        for node in part_shapes:
            n=lambda key:float(field(node,key) or 0)
            x,y=n("X"),n("Y")
            color="#%06x" % (int(field(node,"FillColor")) & 0xffffff)
            if node.tagName=="Oval":
                rx,ry=n("RadiusX"),n("RadiusY")
                draw.ellipse((cx+(x-rx)*scale,cy+(y-ry)*scale,cx+(x+rx)*scale,cy+(y+ry)*scale),fill=color)
            else:
                from math import cos, sin, radians
                theta=radians(n("Rotation"))
                w,h=n("Width"),n("Height")
                draw.polygon([(cx+(x+a*cos(theta)-b*sin(theta))*scale,cy+(y+a*sin(theta)+b*cos(theta))*scale)
                              for a,b in ((0,0),(w,0),(w,h),(0,h))],fill=color)

    cards=[("Пустой поддон","pallet"),("Поддон с листом","sheet"),("Деталь","part"),
           ("Обычная открытая","o"),("Обычная упакованная","oc"),("Хрупкая открытая","f"),
           ("Хрупкая упакованная","fc"),("Ручная открытая","m"),("Ручная упакованная","mc")]
    prefixes={"o":"","f":"fragile_","m":"manual_"}
    for i,(label,state) in enumerate(cards):
        x,y=10+i%3*400,10+i//3*215
        draw.rounded_rectangle((x,y,x+380,y+197),radius=13,fill="white",outline="#b8cdc8",width=2)
        draw.text((x+20,y+15),label,fill="#193a39",font=font)
        if state in {"pallet","sheet"}:
            for row in (0,20,40):
                draw.rectangle((x+119,y+80+row,x+250,y+94+row),fill=tint("palletSlat0"))
            if state=="sheet":
                draw.rectangle((x+145,y+74,x+230,y+142),fill=tint("sheet"))
        elif state=="part":
            draw_part(x+190,y+112,5)
        else:
            draw.rectangle((x+140,y+71,x+241,y+152),fill=tint(prefixes[state[0]]+"carton2D"))
            if len(state)==2:
                draw.rectangle((x+185,y+71,x+196,y+152),fill=tint("tape2D"))
            else:
                draw.rectangle((x+152,y+83,x+229,y+141),fill=tint("openInterior2D"))
                draw_part(x+189,y+115,2.6)
            mark={"f":"▾","m":"Р"}.get(state[0])
            if mark:
                draw.text((x+156,y+96),mark,fill="#142d38",font=font)
    image.save(out)
