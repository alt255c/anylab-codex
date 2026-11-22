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


def record_tour(model, destination, seconds=32, speed=3):
    """One live run: 2D first, then a camera travelling over the conveyor."""
    import json, subprocess, os
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
    put(child(model_xml,"Experiments/SimulationExperiment/ModelTimeProperties"),"FinalTime","36000")
    put(window,"FollowCamera","true")
    put(window,"FarClippingDistance","10000")
    # A fitted overview belongs only to the recording copy, not the ALP profile.
    areas={field(a,"Name"):a for a in children(child(main,"Areas"),"Area")}
    width=1333
    for key,value in {"X":"-700","Y":"-160","Width":str(width),"Height":"800"}.items():
        put(areas["viewLogic"],key,value)
    put(areas["view3D"],"X","5000")
    put(window,"X","5000")
    zoom=1000.0/width
    put(main,"StartupCode","selectedViewArea=viewLogic; viewLogic.navigateTo(); getPresentation().setZoomAndPanningEnabled(false); panelGroup.setScale("+str(1/zoom)+"); panelGroup.setPos("+str(-700+width/2)+","+str(-160+20/zoom)+"); rectangle.setWidth(1000);")
    route=([[-520,500,370,35,-45],[50,350,200,35,-45],[450,450,300,35,-45],[1300,600,350,35,-45],[-500,1550,1300,35,-45]] if full else
           [[-300,500,330,35,-45],[50,350,200,35,-45],[450,450,300,35,-45],[800,500,350,35,-45],[-350,1050,800,35,-45]])
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
        if (!tour3D[0]) {
            double t2 = tourEpoch[0] < 0 ? 0 : Math.max(0,System.nanoTime()/1e9-tourEpoch[0]);
            double u2 = Math.max(0,Math.min(1,(t2-TWO*.2)/(TWO*.6)));
            u2=u2*u2*(3-2*u2);
            double left=-700+PAN*u2;
            viewLogic.setX(left);
            viewLogic.navigateTo();
            panelGroup.setScale(1/ZOOM);
            panelGroup.setPos(left+WIDTH/2,TOP+20/ZOOM);
        }
        if (tourEpoch[0] >= 0) {
            double elapsed = System.nanoTime() / 1e9 - tourEpoch[0];
            if (elapsed >= DURATION+2.5) {
                viewLogic.setX(-700); viewLogic.setY(-400);
                viewLogic.setWidth(OVERVIEW); viewLogic.setHeight(OVERVIEW*.6);
                viewLogic.navigateTo(); selectedViewArea=viewLogic;
                panelGroup.setScale(OVERVIEW/1000.0);
                panelGroup.setPos(-700+OVERVIEW/2.0,-400+20*OVERVIEW/1000.0);
                return;
            }
            if (elapsed >= TWO) {
                if (!tour3D[0]) { panelGroup.setScale(1); navigate(view3D); tour3D[0] = true; }
                view3D.navigateTo();
                panelGroup.setPos(5500,20);
                double progress = Math.max(0, elapsed-TWO) * 24.0 / THREE;
                // Five sequential stations: 3-second holds, 2.25-second moves.
                double step=5.25;
                int station=Math.min(tourRoute.length-1,(int)(progress/step));
                int segment=Math.min(tourRoute.length-2,station);
                double local=progress-station*step;
                double u=(station==tourRoute.length-1) ? 1 : Math.max(0,Math.min(1,(local-3)/2.25));
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
""".replace("ROUTE",literal).replace("MARKER",json.dumps(str(marker),ensure_ascii=False)).replace("ZOOM",str(zoom)).replace("OVERVIEW",str(2700 if full else 1900)).replace("TOP","-160").replace("PAN",str(1450 if full else 650)).replace("WIDTH",str(width)).replace("TWO",str(seconds*.25)).replace("THREE",str(seconds*.75)).replace("DURATION",str(seconds))
    put(main,"StartupCode",field(main,"StartupCode")+code)
    path.write_bytes(doc.toxml(encoding="UTF-8"))
    evidence=anylab.run_model(path,root/"video-run",experiment,180,until="started",close=False)
    try:
        for _ in range(40):
            window=next((w for w in anylab.native(["windows"]) if evidence["project"] in w["title"]),None)
            if window:
                (root/"ready.json").write_text(json.dumps(window,ensure_ascii=False),encoding="utf-8")
                time.sleep(3)
                anylab.native(["capture","--window",window["hwnd"],"--out",root/"ready.png"])
                if os.environ.get("ANYLAB_TOUR_WAIT_FOR_START") == "1":
                    for _ in range(600):
                        if (root/"record-now").exists(): break
                        time.sleep(.2)
                    else: raise TimeoutError("Не получен сигнал начала записи")
                marker.touch()
                anylab.native(["record","--window",window["hwnd"],"--out",root/"demo.mp4","--seconds",seconds])
                time.sleep(4)
                anylab.native(["capture","--window",window["hwnd"],"--out",root/"scene.png"])
                (root/"tour.json").write_text(json.dumps({"live_single_run":True,"seconds":seconds,"2d_seconds":seconds*.25,"camera_route":route,"hold_seconds":seconds*.75/8,"angles_degrees":[35,-45]},indent=2),encoding="utf-8")
                return {"video":str(root/"demo.mp4"),"tour":str(root/"tour.json")}
            time.sleep(.5)
        raise RuntimeError("Окно записи не появилось")
    finally:
        close_owned(evidence["project"].removeprefix("AnyLab_"))
        if evidence.get("owned_ide_pid"):
            subprocess.run(["taskkill","/PID",str(evidence["owned_ide_pid"]),"/F"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
