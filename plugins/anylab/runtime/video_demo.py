"""Record a separate live simulation so a completed statistics run stays reproducible."""
import shutil
import time
from pathlib import Path
from xml.dom import minidom

import anylab
from bridge.anylogic import close_owned, direct, field, put, hook


def presentation_copy(model, folder, three_d, speed=1):
    shutil.copytree(model.parent, folder)
    target = folder / model.name
    doc = minidom.parse(str(target))
    simulations = doc.getElementsByTagName("SimulationExperiment")
    if not simulations:
        raise ValueError("Для видео нужен эксперимент Simulation в проекте")
    experiment = simulations[0]
    settings = direct(experiment, "PresentationProperties")[0]
    if field(settings,"ExecutionMode") != "realTimeScaled":
        put(settings,"ExecutionMode","realTimeScaled")
    put(settings,"RealTimeScale",str(speed))
    agent = next(a for a in doc.getElementsByTagName("ActiveObjectClass")
                 if field(a,"Id") == experiment.getAttribute("ActiveObjectClassId"))
    if three_d:
        window = next((w for w in agent.getElementsByTagName("Control") if w.getAttribute("Type")=="Window3D"),None)
        if window is None:
            raise ValueError("В корневом агенте нет окна 3D. Выберите запись текущего вида.")
        # Fill the default presentation frame with the model's own live 3D control.
        # Move only the viewport, leaving all physical markup and camera coordinates intact.
        frame = doc.getElementsByTagName("Frame")[0]
        for key,val in (("X","0"),("Y","0"),("Width",field(frame,"Width") or "1000"),
                        ("Height",field(frame,"Height") or "600")):
            put(window,key,val)
        window.parentNode.appendChild(window)
        startup = field(agent,"StartupCode")
        if "navigate(viewArea2D);" in startup:
            put(agent,"StartupCode",startup.replace("navigate(viewArea2D);",""))
    target.write_bytes(doc.toxml(encoding="utf-8"))
    return target, field(experiment,"Name")


def record_demo(model, root, files, seconds, three_d, minutes, speed=1, screenshot=False):
    if not isinstance(speed,(int,float)) or not 0.1 <= speed <= 20:
        raise ValueError("Скорость демонстрации должна быть от 0,1 до 20")
    path,experiment = presentation_copy(Path(model),root/"video-project",three_d,speed)
    evidence = anylab.run_model(path,root/"video-run",experiment,min(180,minutes*60),until="started",close=False)
    try:
        for _ in range(30):
            window=next((w for w in anylab.native(["windows"]) if evidence["project"] in w["title"]),None)
            if window:
                time.sleep(3)
                anylab.native(["record","--window",window["hwnd"],"--out",files/"demo.mp4","--seconds",seconds])
                if screenshot:
                    anylab.native(["capture","--window",window["hwnd"],"--out",files/"scene.png"])
                return
            time.sleep(.5)
        raise ValueError("Окно симуляции не появилось для записи")
    finally:
        close_owned(evidence["project"].removeprefix("AnyLab_"))
