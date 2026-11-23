"""Live 2D then smooth 3D tours for pedestrian and road templates, in recording copies."""
import json, math, os, shutil, subprocess, time
from pathlib import Path
from models import child, children, load
from bridge.anylogic import field, put, close_owned
from conveyor import LineEditor, by_name


def route_for(main):
    cameras={field(c,'Name'):c for c in main.getElementsByTagName('Camera3D')}
    def position(name):return [float(field(cameras[name],k)) for k in ['X','Y','Z','RotationX','RotationZ']]
    if 'cameraHallSide1' in cameras:
        names=['cameraEntrySide1','cameraHallSide1','cameraHallSide2','cameraSMEntry','cameraSMFloors','cameraSMIn','cameraSMTop']
        return '4.2', [position(n) for n in names], names
    if 'cameraDispenser1' in cameras:
        # Keep the original overview and follow the row of pumps slowly.
        route=[position('camera'),[696,610,166.21,27.84,-119.55],
               [570,700,150,27.84,-119.55],[696,850,166.21,27.84,-119.55],position('camera')]
        has_payment=any(field(n,'Name')=='driverSource' for n in main.getElementsByTagName('EmbeddedObject'))
        return '6',route,['Общий вид','Первая пара колонок','Кассы и путь водителя' if has_payment else 'Обслуживание у здания','Вторая пара колонок','Общий вид и выезд']
    if 'camera' in cameras:
        p=position('camera')
        return '4.1',[p,[p[0]+300,p[1],p[2]+80,p[3],p[4]],
                      [2956,1178,252,45,-35],p],['Турникеты и автоматы','Лестницы и платформа','Второй вестибюль','Первый вестибюль']
    raise ValueError('Нет профиля камеры ЛР4/ЛР6; задайте камеры модели перед записью')


def prepare_scene_tour(source, folder, seconds=96, speed=3, warmup=20):
    if type(seconds) is not int or not 30<=seconds<=300:raise ValueError('Проход ЛР4/ЛР6: 30–300 секунд')
    if not .1<=speed<=20 or not 0<=warmup<=120:raise ValueError('Неверная скорость или ожидание')
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=False)
    shutil.copytree(Path(source).parent,folder/'project')
    target=folder/'project'/Path(source).name;doc,model=load(target)
    from projects import copy_resources
    copy_resources(Path(source),folder/'project',False)
    main=by_name(child(model,'ActiveObjectClasses'),'ActiveObjectClass')['Main']
    profile,route,labels=route_for(main)
    editor=LineEditor(doc,model,main)
    # Use native area descriptors even when the original model has only a 3D window.
    _,reference=load(Path(__file__).parent/'templates/models/6.1/1/Model.alp')
    ref=by_name(child(reference,'ActiveObjectClasses'),'ActiveObjectClass')['Main']
    prototype=next(n for n in ref.getElementsByTagName('Area') if field(n,'Name')=='view2D')
    areas=child(main,'Areas')
    if areas is None:areas=main.appendChild(doc.createElement('Areas'))
    area2=editor.clone(prototype,'anylabTour2D');area3=editor.clone(prototype,'anylabTour3D')
    bounds=([100,400,1700,1100] if profile in {'4.1','4.2'} else [0,0,1200,800])
    window=next(n for n in main.getElementsByTagName('Control') if n.getAttribute('Type')=='Window3D')
    for a,b in [(area2,bounds),(area3,[float(field(window,k)) for k in ['X','Y','Width','Height']])]:
        for k,v in zip(['X','Y','Width','Height'],b):put(a,k,str(v))
        areas.appendChild(a)
    camera=field(window,'Camera');put(window,'FollowCamera','true');put(window,'FarClippingDistance','15000')
    exp=children(child(model,'Experiments'),'SimulationExperiment')[0]
    settings=child(exp,'PresentationProperties');put(settings,'ExecutionMode','realTimeScaled');put(settings,'RealTimeScale',str(speed))
    put(child(exp,'ModelTimeProperties'),'FinalTime','100000')
    first=min(12,seconds*.2);move=3.;hold=(seconds-first-move*(len(route)-1))/len(route)
    if hold<3:raise ValueError('Недостаточно времени для остановок камеры; увеличьте seconds')
    marker=folder/'begin-tour'
    literal='new double[][]{'+','.join('{'+','.join(map(str,p))+'}' for p in route)+'}'
    code='''
final double[][] sceneRoute=ROUTE;
final double[] sceneStart={-1};
anylabTour2D.navigateTo();
getPresentation().setZoomAndPanningEnabled(false);
class AnyLabSceneTour extends com.anylogic.engine.DynamicEvent {
 AnyLabSceneTour(){super(Main.this,.1);}
 @Override public void execute(){
  double now=System.nanoTime()/1e9;
  if(sceneStart[0]<0 && java.nio.file.Files.exists(java.nio.file.Path.of(MARKER)))sceneStart[0]=now;
  double t=sceneStart[0]<0?0:now-sceneStart[0];
  if(t<FIRST){
   double pan=Math.max(0,Math.min(1,(t-FIRST*.2)/(FIRST*.6)));pan=pan*pan*(3-2*pan);
   anylabTour2D.setX(PANSTART+PANDIST*pan);anylabTour2D.navigateTo();
  }
  else{
   anylabTour3D.navigateTo();
   double elapsed=t-FIRST;int at=Math.min(sceneRoute.length-1,(int)(elapsed/(HOLD+MOVE)));
   int next=Math.min(sceneRoute.length-1,at+1);
   double u=Math.max(0,Math.min(1,(elapsed-at*(HOLD+MOVE)-HOLD)/MOVE));u=u*u*(3-2*u);
   double[] v=new double[5];
   for(int k=0;k<5;k++){
    double delta=sceneRoute[next][k]-sceneRoute[at][k];
    if(k>=3)delta=((delta+540)%360)-180;
    v[k]=sceneRoute[at][k]+delta*u;
   }
   CAMERA.setPos(v[0],v[1],v[2]);CAMERA.setRotationX(Math.toRadians(v[3]));CAMERA.setRotationZ(Math.toRadians(v[4]));CAMERA.update();
  }
  if(t<DURATION+1)new AnyLabSceneTour();
 }
}
new AnyLabSceneTour();
'''.replace('ROUTE',literal).replace('MARKER',json.dumps(str(marker),ensure_ascii=False)).replace('FIRST',str(first)).replace('HOLD',str(hold)).replace('MOVE',str(move)).replace('CAMERA',camera).replace('DURATION',str(seconds)).replace('PANSTART',str(bounds[0])).replace('PANDIST','2100' if profile in {'4.1','4.2'} else '0')
    put(main,'StartupCode',field(main,'StartupCode')+code)
    target.write_bytes(doc.toxml(encoding='UTF-8'))
    manifest=dict(profile=profile,route=route,labels=labels,seconds=seconds,two_d_seconds=first,hold_seconds=hold,transition_seconds=move,live_single_run=True,source=str(Path(source).resolve()))
    (folder/'tour.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    return target,field(exp,'Name'),marker,manifest


def record_scene_tour(source,destination,seconds=96,speed=3,warmup=20):
    import anylab
    root=Path(destination).resolve();model,experiment,marker,manifest=prepare_scene_tour(source,root,seconds,speed,warmup)
    evidence=anylab.run_model(model,root/'run',experiment,180,until='started',close=False)
    try:
        for _ in range(40):
            window=next((w for w in anylab.native(['windows']) if evidence['project'] in w['title']),None)
            if window:break
            time.sleep(.5)
        else:raise RuntimeError('Окно AnyLogic не появилось')
        time.sleep(warmup);anylab.native(['capture','--window',window['hwnd'],'--out',root/'start.png'])
        marker.touch()
        anylab.native(['record','--window',window['hwnd'],'--out',root/'demo.mp4','--seconds',seconds])
        anylab.native(['capture','--window',window['hwnd'],'--out',root/'end.png'])
        return dict(video=str(root/'demo.mp4'),tour=str(root/'tour.json'))
    finally:
        close_owned(evidence['project'].removeprefix('AnyLab_'))
        if evidence.get('owned_ide_pid'):subprocess.run(['taskkill','/PID',str(evidence['owned_ide_pid']),'/F'],capture_output=True)
