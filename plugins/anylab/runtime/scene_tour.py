"""Live 2D then smooth 3D tours for pedestrian and road templates, in recording copies."""
import json, shutil, time
from pathlib import Path
from models import child, children, load
from bridge.anylogic import field, put, close_recording_run
from conveyor import LineEditor, by_name, set_param
from logic_view import add_logic_view


def route_for(main):
    cameras={field(c,'Name'):c for c in main.getElementsByTagName('Camera3D')}
    def position(name):return [float(field(cameras[name],k)) for k in ['X','Y','Z','RotationX','RotationZ']]
    if 'cameraSMEntry' in cameras:
        names=['cameraEntrySide1','cameraHallSide1','cameraTrains1','cameraSMEntry','cameraSMFloors','cameraSMIn','cameraSMTop']
        return '4.2', [position(n) for n in names], ['Вход в метро','Вестибюль','Посадка в поезд','Вход в ТЦ','Галерея ТЦ','Внутри ТЦ','ТЦ сверху']
    if 'cameraDispenser1' in cameras:
        has_payment=any(field(n,'Name') in {'driverSource','выходВодителя'} for n in main.getElementsByTagName('EmbeddedObject'))
        route=[position('camera'),[704,411,34,15,-130],
               [393,407,40,17,-130] if has_payment else [642,445,36,16,-130],
               [tanker_camera_x(main),451,67,28,-113],[1050,805,165,30,-130],position('camera')]
        return '6',route,['Общий вид','Заправка под навесом','Касса со стороны перехода' if has_payment else 'Колонки со стороны выезда',
                          'Служебный проезд со стороны шланга','Выезд и объезд','Общий вид площадки']
    if 'cameraTrains1' in cameras:
        names=['cameraEntrySide1','cameraTrains1','cameraTrains2','cameraHallSide2']
        return '4.1',[position(n) for n in names],['Вход и турникеты','Посадка · путь 1','Посадка · путь 2','Второй вестибюль']
    if 'camera' in cameras:
        p=position('camera')
        return '4.1',[p,[p[0]+300,p[1],p[2]+80,p[3],p[4]],
                      [2956,1178,252,45,-35],p],['Турникеты и автоматы','Лестницы и платформа','Второй вестибюль','Первый вестибюль']
    raise ValueError('Нет профиля камеры ЛР4/ЛР6; задайте камеры модели перед записью')


def tanker_camera_x(main):
    return next((float(field(road,"X"))+57 for road in main.getElementsByTagName("Road")
                 if field(road,"Name")=="tankerRoad"),255)


def limit_metro_demo_flow(editor, single_hall):
    """Keep the film legible while the experiment grid keeps its original rates."""
    street_metro=[block for name,block in editor.blocks.items() if name.startswith("inEntry") and name.endswith("Source")]
    entry_budget=900 if single_hall else 1380
    for block in street_metro:
        set_param(block,"rate",f"Math.min(ИнтенсивностьВход, {entry_budget/len(street_metro):g})")
    for n in (1,2):
        set_param(editor.blocks[f"outTrain{n}Source"],"rate",f"Math.min(ИнтенсивностьВыход, {140 if single_hall else 200})")
        street=editor.blocks.get(f"streetSource{n}")
        if street is not None:
            set_param(street,"rate","Math.min(ИнтенсивностьУлица, 150)")


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
    if profile.startswith("4"):
        single_hall=any(node.firstChild and node.firstChild.data in
                        {"metro_plan_klenovy_bulvar.png","metro_plan_nagatinsky_zaton.png"}
                        for node in model.getElementsByTagName("Path"))
        limit_metro_demo_flow(editor,single_hall)
    # Use native area descriptors even when the original model has only a 3D window.
    _,reference=load(Path(__file__).parent/'templates/models/6.1/1/Model.alp')
    ref=by_name(child(reference,'ActiveObjectClasses'),'ActiveObjectClass')['Main']
    prototype=next(n for n in ref.getElementsByTagName('Area') if field(n,'Name')=='view2D')
    areas=child(main,'Areas')
    if areas is None:areas=main.appendChild(doc.createElement('Areas'))
    area2=editor.clone(prototype,'anylabTour2D');area3=editor.clone(prototype,'anylabTour3D')
    bounds={"4.1":[-90,-125,4200,2480],"4.2":[-120,-830,4320,3080]}.get(profile,[-50,0,1280,925])
    window=next(n for n in main.getElementsByTagName('Control') if n.getAttribute('Type')=='Window3D')
    view3=by_name(areas,'Area').get('viewArea3D')
    for a,b in [(area2,bounds),(area3,[float(field(view3 or window,k)) for k in ['X','Y','Width','Height']])]:
        for k,v in zip(['X','Y','Width','Height'],b):put(a,k,str(v))
        areas.appendChild(a)
    camera=field(window,'Camera');put(window,'FollowCamera','true');put(window,'FarClippingDistance','15000')
    add_logic_view(editor)
    exp=children(child(model,'Experiments'),'SimulationExperiment')[0]
    settings=child(exp,'PresentationProperties');put(settings,'ExecutionMode','realTimeScaled');put(settings,'RealTimeScale',str(speed))
    put(child(exp,'ModelTimeProperties'),'FinalTime','100000')
    first=min(12,seconds*.2);move=3.;hold=(seconds-first-move*(len(route)-1))/len(route)
    if hold<3:raise ValueError('Недостаточно времени для остановок камеры; увеличьте seconds')
    from video_plan import load_plan
    route,timing,chosen_plan=load_plan(source,route,dict(two_d_seconds=first,holds=[hold]*len(route),moves=[move]*(len(route)-1),starts=[first+i*(hold+move) for i in range(len(route))]),seconds)
    first=timing['two_d_seconds']
    move=timing['moves'][0]
    cadence=float(speed)/(30*{'Second':1,'Minute':60,'Hour':3600}.get(field(model,'ModelTimeUnit'),1))
    labels=chosen_plan.get('stop_labels',labels) if chosen_plan else labels
    controls={field(node,'Name'):node for node in main.getElementsByTagName('Control') if node.getAttribute('Type')=='Button'}
    buttons={'4.1':['button2','button4','button5','button1'],
             '4.2':['button2','button','button4','button8','button7','button10','button6']}.get(profile,[])
    buttons=buttons if all(name in controls for name in buttons) and not (chosen_plan and 'camera_route' in chosen_plan) else []
    button_labels=[]
    if buttons:
        camera_node=next(node for node in main.getElementsByTagName('Camera3D') if field(node,'Name')==camera)
        camera='anylabTourCamera'
        camera_node.parentNode.appendChild(editor.clone(camera_node,camera))
        put(window,'Camera',camera)
        for name in buttons:
            basic=child(controls[name],'BasicProperties')
            put(basic,'ActionCode',field(basic,'ActionCode').replace('false, 500','false, 0'))
            button_labels.append(field(child(controls[name],'ExtendedProperties'),'LabelText'))
    marker=folder/'begin-tour'
    switch=folder/'three-d-started'
    literal='new double[][]{'+','.join('{'+','.join(map(str,p))+'}' for p in route)+'}'
    code='''
final double[][] sceneRoute=ROUTE;
final double[] sceneHolds=HOLDS_ARRAY;
final double[] sceneStarts=STARTS_ARRAY;
final com.anylogic.engine.presentation.ShapeButton[] sceneButtons=new com.anylogic.engine.presentation.ShapeButton[]{BUTTONS};
final String[] sceneButtonLabels=BUTTON_LABELS;
final int[] selectedButton={-1};
final boolean[] sceneTravelling={false};
final boolean[] sceneDiagram={false};
final double[] sceneStart={-1};
final boolean[] sceneThreeD={false};
final double[][] sceneLast={null};
anylabTour2D.navigateTo();
getPresentation().setZoomAndPanningEnabled(false);
class AnyLabSceneTour extends com.anylogic.engine.DynamicEvent {
 AnyLabSceneTour(){super(Main.this,CADENCE);}
 @Override public void execute(){
  double now=System.nanoTime()/1e9;
  if(sceneStart[0]<0 && java.nio.file.Files.exists(java.nio.file.Path.of(MARKER)))sceneStart[0]=now;
  double t=sceneStart[0]<0?0:now-sceneStart[0];
  if(t>=FIRST*0.54 && t<FIRST && !sceneDiagram[0]) {
   anylabBlockDiagram.navigateTo(); sceneDiagram[0]=true;
  }
  if(t>=FIRST){
   if(!sceneThreeD[0]){
    anylabTour3D.navigateTo();sceneThreeD[0]=true;
    try {java.nio.file.Files.writeString(java.nio.file.Path.of(SWITCH_PATH),Double.toString(t));}
    catch(java.io.IOException e){throw new RuntimeException(e);}
   }
   int at=0; while(at<sceneRoute.length-1 && t>=sceneStarts[at+1])at++;
   int next=Math.min(sceneRoute.length-1,at+1);
   double u=Math.max(0,Math.min(1,(t-sceneStarts[at]-sceneHolds[at])/MOVE));u=u*u*(3-2*u);
   double[] v=new double[5];
   for(int k=0;k<5;k++){
    double delta=sceneRoute[next][k]-sceneRoute[at][k];
    if(k>=3)delta=((delta+540)%360)-180;
    v[k]=sceneRoute[at][k]+delta*u;
   }
   if(!java.util.Arrays.equals(v,sceneLast[0])){
    CAMERA.setPos(v[0],v[1],v[2]);CAMERA.setRotationX(Math.toRadians(v[3]));CAMERA.setRotationZ(Math.toRadians(v[4]));CAMERA.update();
    sceneLast[0]=v;
   }
   if(sceneButtons.length>0 && selectedButton[0]!=at){
    if(selectedButton[0]>=0)sceneButtons[selectedButton[0]].setText(sceneButtonLabels[selectedButton[0]]);
    selectedButton[0]=at;
    sceneButtons[at].executeUserAction("");
    sceneButtons[at].setText("▶ "+sceneButtonLabels[at]);
    sceneTravelling[0]=false;
   }
   if(sceneButtons.length>0 && u>0 && u<1 && !sceneTravelling[0]){
    WINDOW.setCamera(CAMERA,false,0);
    sceneTravelling[0]=true;
   }
  }
  if(t<DURATION+1)new AnyLabSceneTour();
 }
}
new AnyLabSceneTour();
'''.replace('ROUTE',literal).replace('MARKER',json.dumps(str(marker),ensure_ascii=False)).replace('SWITCH_PATH',json.dumps(str(switch),ensure_ascii=False)).replace('FIRST',str(first)).replace('HOLDS_ARRAY','new double[]{'+','.join(map(str,timing['holds']))+'}').replace('STARTS_ARRAY','new double[]{'+','.join(map(str,timing['starts']))+'}').replace('MOVE',str(move)).replace('CAMERA',camera).replace('DURATION',str(seconds)).replace('CADENCE',str(cadence))
    code=code.replace('BUTTONS',','.join(buttons)).replace('BUTTON_LABELS','new String[]{'+','.join(json.dumps(label,ensure_ascii=False) for label in button_labels)+'}').replace('WINDOW',field(window,'Name'))
    put(main,'StartupCode',field(main,'StartupCode')+code)
    target.write_bytes(doc.toxml(encoding='UTF-8'))
    manifest=dict(profile=profile,route=route,labels=labels,seconds=seconds,two_d_seconds=first,
                  diagram_start_seconds=first*.54,buttons=buttons,hold_seconds=(timing['holds'] if chosen_plan else hold),
                  station_hold_seconds=timing['holds'],transition_seconds=move,live_single_run=True,source=str(Path(source).resolve()))
    (folder/'tour.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    return target,field(exp,'Name'),marker,manifest


def record_scene_tour(source,destination,seconds=96,speed=3,warmup=20,profile="hd"):
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
        fps=30 if profile=='hd' else 12
        anylab.native(['record','--window',window['hwnd'],'--out',root/'demo.mp4','--seconds',seconds,
                       '--profile',profile,'--fps',fps,'--start-marker',marker])
        switch=root/'three-d-started'
        if not switch.is_file():
            raise RuntimeError("Демонстрация не переключилась в 3D. Проверьте журнал запуска AnyLogic.")
    finally:
        close_recording_run(evidence,root/'run')
    return dict(video=str(root/'demo.mp4'),tour=str(root/'tour.json'))
