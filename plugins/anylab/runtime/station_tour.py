"""Prepare the choreography in a separate station ALP for the capture run."""
import json
import math
from pathlib import Path
import shutil
from xml.dom import Node
import time

from bridge.anylogic import field,put,close_recording_run
from conveyor import LineEditor,by_name
from models import child

def parameter(block,name,code):
 params=child(block,"Parameters")
 existing=by_name(params,"Parameter")
 if name not in existing:
  p=block.ownerDocument.createElement("Parameter");put(p,"Name",name);params.appendChild(p)
 else:p=existing[name]
 v=child(p,"Value")
 if v is None:
  v=block.ownerDocument.createElement("Value");v.setAttribute("Class","CodeValue");p.appendChild(v)
 put(v,"Code",code)

def on(block,name,code):
 item=by_name(child(block,"Parameters"),"Parameter").get(name)
 value=child(item,"Value") if item else None
 parameter(block,name,(field(value,"Code") if value else "")+"\n"+code)

def prepare(source, out, pilot=False, speed=1):
 if type(speed) not in (int,float) or not .5<=speed<=4:
  raise ValueError("Скорость показа АЗС должна быть от 0,5× до 4×")
 source=Path(source).resolve(strict=True)
 out=Path(out).resolve()
 part=2 if "выходВодителя" in source.read_text(encoding="utf-8") else 1
 folder=out/"Проект съёмки"
 shutil.copytree(source.parent,folder,ignore=shutil.ignore_patterns("*.mp4"))
 target=folder/source.name
 from models import load
 doc,model=load(target)
 put(model,"ModelTimeUnit","Second")
 classes=by_name(child(model,"ActiveObjectClasses"),"ActiveObjectClass")
 main=classes["Main"]
 from station_layout import fix_station_layout
 fix_station_layout(doc,model,main)
 exp=child(model,"Experiments/SimulationExperiment")
 experiments=child(model,"Experiments")
 for e in list(experiments.childNodes):
  if e.nodeType==Node.ELEMENT_NODE and e is not exp:experiments.removeChild(e)
 put(exp,"Name","Демонстрация")
 pp=child(exp,"PresentationProperties")
 put(pp,"ExecutionMode","virtualTime" if pilot else "realTimeScaled")
 put(pp,"RealTimeScale",str(speed))
 if not pilot:put(pp,"EnableZoomAndPanning","false")
 put(pp,"Title","Автозаправочная станция — непрерывная демонстрация")
 tp=child(exp,"ModelTimeProperties")
 put(tp,"StopOption","Stop at specified time" if pilot else "Never")
 put(tp,"FinalTime","800")
 areas=by_name(child(main,"Areas"),"Area")
 for k,v in {"X":0,"Y":0,"Width":1250,"Height":810}.items():put(areas["view2D"],k,str(v))
 for k,v in {"Width":1510,"Height":842}.items():put(areas["view3D"],k,str(v))
 windows=by_name(child(child(child(main,"Presentation"),"Level"),"Presentation"),"Control")
 w=windows["window3d"]
 for name,o in windows.items():
  if name.startswith("window3dDispenser"):
   for key,value in {"X":5000,"Width":16,"Height":16,"FollowCamera":"false"}.items():
    put(o,key,str(value).lower())
 for k,v in {"X":0,"Y":1252,"Width":1492,"Height":777,"FollowCamera":"true","FarClippingDistance":10000}.items():
  put(w,k,str(v))
 editor=LineEditor(doc,model,main)
 from logic_view import add_logic_view
 add_logic_view(editor)
 level=child(child(child(main,"Presentation"),"Level"),"Presentation")
 menu=child(by_name(level,"Group")["groupMainMenu"],"Presentation")
 title=editor.clone(by_name(menu,"Text")["text4"],"подписьРежиссёра")
 for k,v in {"X":444,"Y":13,"Color":"-14665434","Text":"","TextCode":"строкаКадра"}.items():put(title,k,str(v))
 font=child(title,"Font");put(font,"Size","20");put(font,"Style","1")
 menu.appendChild(title)
 variables=child(main,"Variables")
 proto=by_name(variables,"Variable")["arrived"]
 for n,j,v in (("кадрМашина","Car","null"),("кадрФон","Car","null"),("кадрВыезд","Car","null"),
                *(("кадрВодитель","Driver","null"),) * (part==2),
                ("геройВыехал","boolean","false"),("геройВернулся","boolean","false"),("геройОплатил","boolean","false"),
                ("кадрВыездНачался","boolean","false"),("кадрВыездЗакончен","boolean","false"),
                ("режиссёрКадра","Runnable","null"),("строкаКадра","String","\"Заезд автомобиля\"")):
  var=editor.clone(proto,n);props=child(var,"Properties")
  put(props,"Type",j);put(child(props,"InitialValue"),"Code",v);variables.appendChild(var)
 blocks=by_name(child(main,"EmbeddedObjects"),"EmbeddedObject")
 source=blocks["прибытиеАвтомобилей"]
 parameter(source,"arrivalType","self.MANUAL")
 for speed_parameter in ("initialSpeed","preferredSpeed"):
  parameter(source,speed_parameter,"14.0")
  parameter(blocks["въездБензовоза"],speed_parameter,"12.0")
 parameter(source,"onExit",'''
arrived++;
car.stationEntry=time();
if(arrived==1) { кадрМашина=car; car.fuelType=GAS95; car.initialFuelAmount=54; }
else { car.fuelType=FuelType.values()[(arrived-2)%3]; car.initialFuelAmount=8;
       if(arrived==2) кадрФон=car; else if(arrived==3) кадрВыезд=car; }
''')
 if part==2:
  on(blocks["выходВодителя"],"onAtExit","if(agent.car==кадрМашина) кадрВодитель=agent;")
  for n in ("оплатаКасса1","оплатаКасса2"):
   on(blocks[n],"onEnter","agent.setSpeed(1.6,MPS);")
   on(blocks[n],"onExit","if(agent==кадрВодитель) геройОплатил=true;")
  on(blocks["возвратВодителя"],"onEnter","if(agent==кадрВодитель) {кадрВодитель=null; геройВернулся=true;}")
 on(blocks["кВыезду"],"onEnter","if(car==кадрВыезд) кадрВыездНачался=true;")
 on(blocks["выездАвтомобиля"],"onEnter",
    "if(car==кадрМашина) геройВыехал=true; if(car==кадрФон) кадрФон=null; if(car==кадрВыезд) кадрВыездЗакончен=true;")
 for b in blocks.values():
  if field(child(b,"ActiveObjectClass"),"ClassName")=="MoveTo":parameter(b,"speed","1.6")
 parameter(blocks["резервуарАИ92"],"initialAmount","29.84")
 parameter(blocks["топливныйШланг"],"maxRate","32")
 events=child(main,"Events")
 events.removeChild(by_name(events,"Event")["ПроверитьТопливо"])
 timer=editor.clone(by_name(events,"Event")["СнятьСтатистику"],"ПоворотКамеры")
 props=child(timer,"Properties");put(props,"Id","1999200008877")
 for k in ("OccurrenceTime","RecurrenceCode"):
  put(child(props,k),"Code",".25" if pilot else str(speed/30))
  put(child(props,k),"Unit","SECOND")
 put(timer,"Action","if(режиссёрКадра!=null) режиссёрКадра.run();")
 events.appendChild(timer)
 hoses=by_name(child(classes["FuelDispenser"],"EmbeddedObjects"),"EmbeddedObject")
 for n in ("шлангАИ92","шлангАИ95","шлангДТ"):
  parameter(hoses[n],"limitRate","true")
  parameter(hoses[n],"maxRate","1.2")
  val=child(by_name(child(hoses[n],"Parameters"),"Parameter")["maxRate"],"Value")
  if child(val,"Unit") is None:
   val.setAttribute("Class","CodeUnitValue")
   put(val,"Unit","LITER_PER_SECOND")
   child(val,"Unit").setAttribute("Class","FlowRateUnits")
 code=Path(__file__).with_suffix(".java").read_text(encoding="utf-8")
 if part==1:
  import re
  code=re.sub(r'    void followDriver\(Driver driver\) \{.*?\n    \}\n', '', code, flags=re.S)
  code=re.sub(r'            if\(person!=null\) \{.*?\n            } else if\(геройВернулся\) \{.*?\n            }\n', '', code, flags=re.S)
  code=code.replace('            Driver person=кадрВодитель;\n','').replace('person==null && ','')
 code=code.replace("PILOT_MODE",str(pilot).lower()).replace("START_PATH",json.dumps(str(out/"tour-start"),ensure_ascii=False)).replace("TRACE_PATH",json.dumps(str(out/"tour-events.csv"),ensure_ascii=False))
 code=code.replace("FINISH_PATH",json.dumps(str(out/"tour-finished"),ensure_ascii=False)).replace("TOUR_SPEED",str(float(speed)))
 put(main,"StartupCode",field(main,"StartupCode")+"\n"+code)
 target.write_bytes(doc.toxml(encoding="utf-8"))
 return target, field(exp,"Name")


def record_station_tour(source, destination, profile="hd", speed=1):
 import anylab
 root=Path(destination).resolve()
 root.mkdir(parents=True,exist_ok=False)
 target,experiment=prepare(source,root,speed=speed)
 evidence=anylab.run_model(target,root/"run",experiment,timeout=160,until="started")
 try:
  for _ in range(40):
   window=next((item for item in anylab.native(["windows"]) if evidence["project"] in item["title"]),None)
   if window:
    break
   time.sleep(.4)
  else:
   raise RuntimeError("Окно демонстрации АЗС не появилось")
  end=root/"tour-finished"
  video=root/"demo.mp4"
  anylab.native(["record","--window",window["hwnd"],"--out",video,"--seconds",math.ceil(420/speed),
                 "--profile",profile,"--fps",30,"--start-marker",root/"tour-start","--finish-marker",end])
  if not end.is_file():
   raise RuntimeError("Демонстрация АЗС не дошла до финального кадра. Подробности в tour-events.csv.")
  phases={}
  for row in (root/"tour-events.csv").read_text(encoding="utf-8").splitlines():
   name,_,wall,*_=row.split(";")
   phases.setdefault(name,float(wall))
  labels=["заправка автомобиля","у кассы","водитель вернулся","другой автомобиль заправляется",
          "другой автомобиль выезжает","слив 2D — начало","слив 3D — половина объёма"]
  matched=[name for name in labels if name in phases]
  manifest=root/"tour.json"
  manifest.write_text(json.dumps({"live_single_run":True,"playback_speed":speed,
                     "two_d_seconds":4,"labels":matched,"station_start_seconds":[phases[name] for name in matched]},
                     ensure_ascii=False,indent=2),encoding="utf-8")
  return {"video":str(video),"tour":str(manifest)}
 finally:
  close_recording_run(evidence,root/"run")
