"""Record a separate live simulation so a completed statistics run stays reproducible."""
import shutil
import time
from pathlib import Path
from xml.dom import minidom

import anylab
from bridge.anylogic import close_owned, direct, field, put


def presentation_copy(model, folder, three_d, speed=1, camera=None):
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
    for viewport in agent.getElementsByTagName("Control"):
        if viewport.getAttribute("Type")=="Window3D":
            put(viewport,"MakeDefaultViewArea","true" if three_d else "false")
    if three_d:
        window = next((w for w in agent.getElementsByTagName("Control") if w.getAttribute("Type")=="Window3D"),None)
        if window is None:
            raise ValueError("В корневом агенте нет окна 3D. Выберите запись текущего вида.")
        if camera:
            selected = next(c for c in agent.getElementsByTagName("Camera3D") if field(c,"Name")==field(window,"Camera"))
            for key,value in camera.items():
                if key not in {"X","Y","Z","RotationX","RotationZ"} or not isinstance(value,(int,float)):
                    raise ValueError("Камера принимает числовые X, Y, Z, RotationX, RotationZ")
                put(selected,key,str(value))
    # Select a tab through the model's own navigation, preserving its window.
    startup=field(agent,"StartupCode")
    put(agent,"StartupCode",startup+"\nnavigate("+("view3D" if three_d else "viewLogic")+");")
    target.write_bytes(doc.toxml(encoding="utf-8"))
    return target, field(experiment,"Name")


def record_demo(model, root, files, seconds, three_d, minutes, speed=1, screenshot=False, camera=None, warmup=3):
    if not isinstance(speed,(int,float)) or not 0.1 <= speed <= 20:
        raise ValueError("Скорость демонстрации должна быть от 0,1 до 20")
    if not 0 <= warmup <= 60:
        raise ValueError("Ожидание наполнения сцены должно составлять 0–60 секунд")
    path,experiment = presentation_copy(Path(model),root/"video-project",three_d,speed,camera)
    evidence = anylab.run_model(path,root/"video-run",experiment,min(180,minutes*60),until="started",close=False)
    try:
        for _ in range(30):
            window=next((w for w in anylab.native(["windows"]) if evidence["project"] in w["title"]),None)
            if window:
                time.sleep(warmup)
                anylab.native(["record","--window",window["hwnd"],"--out",files/"demo.mp4","--seconds",seconds])
                if screenshot:
                    anylab.native(["capture","--window",window["hwnd"],"--out",files/"scene.png"])
                return
            time.sleep(.5)
        raise ValueError("Окно симуляции не появилось для записи")
    finally:
        close_owned(evidence["project"].removeprefix("AnyLab_"))
        if evidence.get("owned_ide_pid"):
            import subprocess
            subprocess.run(["taskkill","/PID",str(evidence["owned_ide_pid"]),"/F"],
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)


def record_tour(model, destination, seconds=20, speed=3):
    """One live run: 2D first, then a camera travelling over the conveyor."""
    import json, subprocess
    if not isinstance(seconds,int) or not 10 <= seconds <= 120:
        raise ValueError("Продолжительность tour: 10–120 секунд")
    if not isinstance(speed,(int,float)) or not 0.1 <= speed <= 20:
        raise ValueError("Скорость tour: 0.1–20")
    from models import load, child, children
    root=Path(destination).resolve();root.mkdir(parents=True,exist_ok=False)
    path,experiment=presentation_copy(Path(model).resolve(strict=True),root/"video-project",False,speed)
    doc,model_xml=load(path)
    main=next(a for a in children(child(model_xml,"ActiveObjectClasses"),"ActiveObjectClass") if field(a,"Name")=="Main")
    if not any(field(a,"Name")=="Carton" for a in children(child(model_xml,"ActiveObjectClasses"),"ActiveObjectClass")):
        raise ValueError("Кинопроход tour настроен для конвейеров ЛР5")
    full=any(field(n,"Name")=="warehouseNetwork" for n in main.getElementsByTagName("Network"))
    window=next(w for w in main.getElementsByTagName("Control") if w.getAttribute("Type")=="Window3D")
    put(window,"FollowCamera","true")
    put(window,"FarClippingDistance","10000")
    route=([[50,350,200,35,-45],[1300,600,350,35,-45],[-500,1550,1300,35,-45]] if full else
           [[50,350,200,35,-45],[600,500,250,35,-45],[-350,1050,800,35,-45]])
    literal="new double[][]{"+",".join("{"+",".join(str(v) for v in row)+"}" for row in route)+"}"
    marker=root/"begin-tour"
    code="""
final double[] tourEpoch = {-1};
final boolean[] tour3D = {false};
final double[][] tourRoute = ROUTE;
class AnyLabLiveCameraTour extends com.anylogic.engine.DynamicEvent {
    AnyLabLiveCameraTour() { super(Main.this, 0.15); }
    @Override public void execute() {
        if (tourEpoch[0] < 0 && java.nio.file.Files.exists(java.nio.file.Path.of(MARKER))) tourEpoch[0] = System.nanoTime() / 1e9;
        if (tourEpoch[0] >= 0) {
            double elapsed = System.nanoTime() / 1e9 - tourEpoch[0];
            if (elapsed >= TWO) {
                if (!tour3D[0]) { navigate(view3D); tour3D[0] = true; }
                double progress = Math.max(0, elapsed-TWO);
                // 3 s hold, 1.5 s move, 3 s hold, 1.5 s move, 3 s hold.
                // Scale this schedule to the requested 3D duration.
                progress = progress * 12.0 / THREE;
                int segment; double u;
                if (progress < 3) { segment=0; u=0; }
                else if(progress < 4.5) { segment=0; u=(progress-3)/1.5; }
                else if(progress < 7.5) { segment=1; u=0; }
                else if(progress < 9) { segment=1; u=(progress-7.5)/1.5; }
                else { segment=1; u=1; }
                u=u*u*(3-2*u);
                double[] v = new double[5];
                for(int k=0;k<5;k++) v[k]=tourRoute[segment][k]*(1-u)+tourRoute[segment+1][k]*u;
                camera.setPos(v[0],v[1],v[2]);
                camera.setRotationX(Math.toRadians(v[3]));
                camera.setRotationZ(Math.toRadians(v[4]));
                camera.update();
            }
            if (elapsed > DURATION+3) return;
        }
        new AnyLabLiveCameraTour();
    }
}
new AnyLabLiveCameraTour();
""".replace("ROUTE",literal).replace("MARKER",json.dumps(str(marker),ensure_ascii=False)).replace("SPEED",str(speed)).replace("TWO",str(seconds*.4)).replace("THREE",str(seconds*.6)).replace("DURATION",str(seconds))
    put(main,"StartupCode",field(main,"StartupCode")+code)
    path.write_bytes(doc.toxml(encoding="UTF-8"))
    evidence=anylab.run_model(path,root/"video-run",experiment,180,until="started",close=False)
    try:
        for _ in range(40):
            window=next((w for w in anylab.native(["windows"]) if evidence["project"] in w["title"]),None)
            if window:
                time.sleep(3)
                marker.touch()
                anylab.native(["record","--window",window["hwnd"],"--out",root/"demo.mp4","--seconds",seconds])
                anylab.native(["capture","--window",window["hwnd"],"--out",root/"scene.png"])
                (root/"tour.json").write_text(json.dumps({"live_single_run":True,"seconds":seconds,"2d_seconds":seconds*.4,"camera_route":route,"hold_seconds":seconds*.15,"angles_degrees":[35,-45]},indent=2),encoding="utf-8")
                return {"video":str(root/"demo.mp4"),"tour":str(root/"tour.json")}
            time.sleep(.5)
        raise RuntimeError("Окно записи не появилось")
    finally:
        close_owned(evidence["project"].removeprefix("AnyLab_"))
        if evidence.get("owned_ide_pid"):
            subprocess.run(["taskkill","/PID",str(evidence["owned_ide_pid"]),"/F"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
