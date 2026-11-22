"""Scenario options for the open-course assignments."""
import math
import shutil
from pathlib import Path

from bridge.anylogic import field, put
from models import anchors, child, children, load, route_curve, set_points


def course_options(lab, station=None, station_plan=None, addition=None):
    if station or station_plan:
        if lab != 4 or not station or not station.strip():
            raise ValueError("Укажите название станции для ЛР4")
    if station and (len(station) > 100 or any(ord(c)<32 for c in station)):
        raise ValueError("Укажите название станции одной строкой")
    if station_plan:
        plan = Path(station_plan).resolve(strict=True)
        if not plan.is_file():
            raise ValueError("План станции должен быть файлом")
        station_plan = str(plan)
    if lab == 4:
        return dict(station=station.strip() if station else None, station_plan=station_plan,
                    layout="station" if station else "generic_lobby")
    if lab == 5:
        return dict(open_examples=["ConveyorEnter","ConveyorExit"],
                    lecture_topics=["Транспортёр","Начало и конец транспортёра"],
                    addition=addition or "Подача детали поперёк линии, сборка на поддоне и три склада")
    if lab == 6:
        return dict(open_examples=["Gas Station","Road Traffic Tutorial - Phase 6"],
                    lecture_topics=["Дорожная библиотека","Авто и водитель"],
                    addition=addition or "Сравнение правил выбора очереди по ожиданию и доле проехавших мимо")
    return {}


def conveyor_scenario(source, destination, rate, horizon=600, seed=1, full_line=False,
                      palette="blue_turquoise_orange", layout="extended_offset",
                      component="blue_sleeve"):
    """Build the lab's finite measurement profile and optional loading/unloading line."""
    from projects import copy_resources, new_directory
    if any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or n<=0
           for n in (rate,horizon)):
        raise ValueError("Интенсивность и горизонт должны быть положительными")
    if type(seed) is not int or not 0<=seed<=2147483647:
        raise ValueError("Зерно должно быть целым числом от 0 до 2147483647")
    palettes={"blue_turquoise_orange":("#19B6B0","#F28A3C"),
              "orange_cream_blue":("#E88448","#2867B2"),
              "green_sand_coral":("#49866F","#E57556")}
    details={"blue_sleeve":"#2867D1","orange_sleeve":"#F28A3C","silver_spool":"#9AA7B3"}
    if palette not in palettes:
        raise ValueError("Выберите палитру: blue_turquoise_orange, orange_cream_blue, green_sand_coral")
    if layout not in {"extended_offset","compact_straight"}:
        raise ValueError("Выберите геометрию: extended_offset или compact_straight")
    if component not in details:
        raise ValueError("Выберите деталь: blue_sleeve, orange_sleeve или silver_spool")
    path = Path(source).resolve(strict=True)
    doc, model = load(path)
    resources = child(model,"ModelResources")
    from bridge.anylogic import locate,version
    _,installed_build=locate()
    source_version=doc.documentElement.getAttribute("AlpVersion")
    if version(source_version)>version(installed_build):
        if version(source_version)[:2]!=version(installed_build)[:2]:
            raise ValueError(f"Шаблон AnyLogic {source_version} новее установленной версии {installed_build}")
        doc.documentElement.setAttribute("AnyLogicVersion",installed_build)
        doc.documentElement.setAttribute("AlpVersion",".".join(installed_build.split(".")[:3]))
    main = next((a for a in children(child(model,"ActiveObjectClasses"),"ActiveObjectClass")
                 if field(a,"Name")=="Main"), None)
    if main is None:
        raise ValueError("Выберите встроенный шаблон средней части конвейера ЛР5")
    parameter = next((p for p in children(child(main,"Variables"),"Variable")
                      if field(p,"Name")=="ИнтенсивностьПрибытия"), None)
    network = next(iter(main.getElementsByTagName("ConveyorNetwork")),None)
    if parameter is None or network is None:
        raise ValueError("Выберите встроенный шаблон средней части конвейера ЛР5")
    # Apply a user-selected, reproducible visual palette to the model assets.
    body_color,accent_color=palettes[palette]
    colors={"MA_material_27":_argb(body_color),"MA_material_28":_argb(accent_color)}
    for mapping in model.getElementsByTagName("ColorMapping"):
        material=field(mapping,"Name")
        if material in colors:
            color=child(mapping,"Color")
            if color is None:
                color=mapping.appendChild(doc.createElement("Color"))
            put(mapping,"Color",str(colors[material]))
    code = child(parameter,"Properties/DefaultValue")
    put(code,"Code",str(rate))
    experiment = child(model,"Experiments/SimulationExperiment")
    put(experiment,"SeedValue",str(seed))
    pp = child(experiment,"PresentationProperties")
    put(pp,"ExecutionMode","virtualTime")
    timing = child(experiment,"ModelTimeProperties")
    put(timing,"StopOption","Stop at specified time")
    put(timing,"FinalTime",str(horizon))
    name="ConveyorLine" if full_line else "ConveyorPacking"
    put(model,"Name",name)
    put(pp,"Title",name+" : Simulation")
    assets = []
    if full_line:
        belts=children(child(network,"Presentation"),"Conveyor")
        if not any(field(b,"Name")=="loadingBelt" for b in belts):
            add_terminal_sections(doc,main,network,layout)
        from conveyor import extend_line
        assets = extend_line(doc, model, main, network,component,layout)
        assets.append(Path("blue_sleeve.dae"))
    else:
        from conveyor import extend_loading
        assets = extend_loading(doc,model,main,network)
        assets.append(Path("blue_sleeve.dae"))
    # Figure3D meshes have no usable bitmap preview in the 2D animation.
    # Let the explicit vector proxies represent moving cartons there, and
    # reserve the imported meshes for the 3D view.
    for figure in model.getElementsByTagName("Figure3D"):
        put(figure,"DrawMode","SHAPE_DRAW_3D")
    dest=Path(destination).resolve()
    with new_directory(dest) as stage:
        copy_resources(path,stage,False)
        for resource in assets:
            relative = Path("3d") / resource.name
            (stage / relative.parent).mkdir(exist_ok=True)
            if resource.name == "blue_sleeve.dae":
                (stage / relative).write_text(_blue_sleeve_dae(details[component]), encoding="utf-8")
                original = next(r for r in children(resources,"Resource") if field(r,"Path")=="3d/pipe_corner.dae")
                replacement = original.cloneNode(True)
                put(replacement,"Path","3d/blue_sleeve.dae")
                resource_id=child(replacement,"Id")
                if resource_id is not None:
                    maximum=max((int(n.firstChild.data) for n in model.getElementsByTagName("Id")
                                 if n.firstChild and n.firstChild.data.isdecimal()),default=0)
                    put(replacement,"Id",str(maximum+1))
                resources.appendChild(replacement)
            else:
                shutil.copy2(resource, stage / relative)
        (stage/(name+".alp")).write_bytes(doc.toxml(encoding="UTF-8"))
    return dict(model=str(dest/(name+".alp")), rate_per_minute=rate, horizon_seconds=horizon,
                seed=seed, full_line=full_line, experiment=field(experiment,"Name"),
                palette=palette, layout=layout, component=component,
                source_model_version=source_version, generated_model_version=doc.documentElement.getAttribute("AlpVersion"))


def _blue_sleeve_dae(color="#2867D1"):
    # Simple original hollow cylinder, authored as COLLADA instead of reusing
    # an illustration from a student report or an unrelated AnyLogic asset.
    import math
    n=20; outer=8.0; inner=4.2; half=10.0
    points=[]
    for x in (-half,half):
        for radius in (outer,inner):
            points.extend((x, radius*math.cos(2*math.pi*i/n), radius*math.sin(2*math.pi*i/n)) for i in range(n))
    faces=[]
    for i in range(n):
        j=(i+1)%n
        faces.extend(((i,j,n+j),(i,n+j,n+i), (2*n+i,3*n+i,3*n+j),(2*n+i,3*n+j,2*n+j),
                      (i,2*n+i,2*n+j),(i,2*n+j,j),(n+i,n+j,3*n+j),(n+i,3*n+j,3*n+i)))
    pos=" ".join(f"{v:.3f}" for p in points for v in p)
    tris=" ".join(str(v) for face in faces for v in face)
    return f'''<?xml version="1.0" encoding="utf-8"?>
<COLLADA xmlns="http://www.collada.org/2005/11/COLLADASchema" version="1.4.1"><asset><contributor><authoring_tool>AnyLab original asset</authoring_tool></contributor><unit name="centimeter" meter="0.01"/><up_axis>Y_UP</up_axis></asset>
<library_effects><effect id="blue"><profile_COMMON><technique sid="common"><lambert><diffuse><color>{int(color[1:3],16)/255:.4f} {int(color[3:5],16)/255:.4f} {int(color[5:7],16)/255:.4f} 1</color></diffuse></lambert></technique></profile_COMMON></effect></library_effects><library_materials><material id="blueMat" name="AnyLab custom component"><instance_effect url="#blue"/></material></library_materials>
<library_geometries><geometry id="sleeve" name="Blue cylindrical sleeve"><mesh><source id="positions"><float_array id="positions-array" count="{len(points)*3}">{pos}</float_array><technique_common><accessor source="#positions-array" count="{len(points)}" stride="3"><param name="X" type="float"/><param name="Y" type="float"/><param name="Z" type="float"/></accessor></technique_common></source><vertices id="vertices"><input semantic="POSITION" source="#positions"/></vertices><triangles material="surface" count="{len(faces)}"><input semantic="VERTEX" source="#vertices" offset="0"/><p>{tris}</p></triangles></mesh></geometry></library_geometries>
<library_visual_scenes><visual_scene id="Scene" name="Scene"><node id="Sleeve"><instance_geometry url="#sleeve"><bind_material><technique_common><instance_material symbol="surface" target="#blueMat"/></technique_common></bind_material></instance_geometry></node></visual_scene></library_visual_scenes><scene><instance_visual_scene url="#Scene"/></scene></COLLADA>'''


def _argb(hex_color):
    value=int(hex_color.lstrip("#"),16) | 0xFF000000
    return value-0x100000000 if value >= 0x80000000 else value


def conveyor_capacity(source,destination,rates=(4,8,12,16,20),horizon=900,seed=73,minutes=12):
    """Sweep a bounded arrival-rate grid and report the measured saturation point."""
    import csv,time
    from anylab import run_model
    from projects import new_directory
    values=list(rates)
    if not values or len(values)>8 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or x<=0 for x in values):
        raise ValueError("Укажите от 1 до 8 положительных уровней интенсивности")
    if not math.isfinite(minutes) or not 1<=minutes<=15:
        raise ValueError("Бюджет серии должен быть от 1 до 15 минут")
    dest=Path(destination).resolve()
    dest.mkdir(parents=True,exist_ok=False)
    started=time.monotonic(); rows=[]
    for index,rate in enumerate(values):
        if time.monotonic()-started>=minutes*60-40:
            break
        model_dir=dest/f"rate-{rate:g}"
        built=conveyor_scenario(source,model_dir,float(rate),horizon,seed,True)
        run_dir=model_dir/"run"
        remaining=max(30,int(minutes*60-(time.monotonic()-started)))
        evidence=run_model(built["model"],run_dir,"Simulation",timeout=min(180,remaining),
                           until="finished",close=True,metrics={
                               "main_arrivals":"source.count()",
                               "manual_arrivals":"source1.count()",
                               "ordinary":"ordinaryDelivered",
                               "fragile":"fragileDelivered",
                               "manual":"manualDelivered"})
        if not evidence.get("finished"):
            rows.append({"rate":rate,"state":evidence.get("state"),"finished":False})
            break
        metrics_path=Path(evidence["metrics_csv"])
        with metrics_path.open(encoding="utf-8",newline="") as stream:
            result=list(csv.DictReader(stream))[-1]
        arrivals=int(float(result["main_arrivals"]))+int(float(result["manual_arrivals"]))
        throughput=sum(int(float(result[k])) for k in ("ordinary","fragile","manual"))
        backlog=max(0,arrivals-throughput)
        rows.append({"rate_per_minute":float(rate),"main_arrivals":int(float(result["main_arrivals"])),
                     "manual_arrivals":int(float(result["manual_arrivals"])),"arrivals":arrivals,"finished_boxes":throughput,
                     "backlog":backlog,"throughput_per_minute":round(throughput*60/horizon,3),
                     "completion_ratio":round(throughput/arrivals,4) if arrivals else 1.0,
                     "sustainable":backlog<=max(3,math.ceil(arrivals*.05)),"finished":True,"run":str(run_dir)})
    sustainable=[r for r in rows if r.get("sustainable")]
    peak=max((r["throughput_per_minute"] for r in rows if "throughput_per_minute" in r),default=None)
    saturation=next((r["rate_per_minute"] for r in sorted(rows,key=lambda r:r.get("rate_per_minute",float("inf")))
                     if peak is not None and r.get("throughput_per_minute",0)>=peak*.95),None)
    result={"runs":rows,"tested_levels":len(rows),"requested_levels":len(values),
            "max_sustainable_rate":max((r["rate_per_minute"] for r in sustainable),default=None),
            "measured_peak_throughput_per_minute":peak,"saturation_onset_rate":saturation,
            "elapsed_seconds":round(time.monotonic()-started,2),
            "complete":len(rows)==len(values) and all(r.get("finished") for r in rows)}
    with (dest/"capacity.csv").open("w",encoding="utf-8-sig",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=sorted({k for row in rows for k in row}))
        writer.writeheader();writer.writerows(rows)
    (dest/"capacity.json").write_text(__import__("json").dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    return result


def add_terminal_sections(doc, main, network, layout="extended_offset"):
    presentation=child(network,"Presentation")
    belts={field(n,"Name"):n for n in children(presentation,"Conveyor")}
    turntable=children(presentation,"Turntable")[0]
    next_id=max(int(n.firstChild.data) for n in doc.getElementsByTagName("Id")
                if n.firstChild and n.firstChild.data.isdecimal())+1

    def clone(node,name):
        nonlocal next_id
        duplicate=node.cloneNode(True)
        put(duplicate,"Name",name)
        for token in duplicate.getElementsByTagName("Id"):
            token.firstChild.data=str(next_id)
            next_id+=1
        return duplicate

    def set_straight(belt,length):
        set_points(belt,route_curve([(0,0,0),(length,0,0)]))

    inlet, outlet=belts["conveyor"],belts["conveyor2"]
    y=field(inlet,"Y")
    # Half of the 2-metre turntable is 33.333 model pixels.
    radius=100/3
    length_in,length_out=(144,166) if layout=="extended_offset" else (110,110)
    first_x=float(field(inlet,"X"))
    last_x=float(field(outlet,"X"))+anchors(outlet)[-1][0]
    connector=clone(turntable,"loadingTransfer")
    put(connector,"X",str(first_x-radius));put(connector,"Y",y)
    belt=clone(inlet,"loadingBelt")
    for section in children(belt,"Presentation"):
        belt.removeChild(section)
    for side in ("SourceId","TargetId"):
        if belt.hasAttribute(side):belt.removeAttribute(side)
    ident=field(connector,"Id")
    belt.setAttribute("TargetId",ident)
    inlet.setAttribute("SourceId",ident)
    put(belt,"X",str(first_x-2*radius-length_in));put(belt,"Y",y);set_straight(belt,length_in)
    presentation.appendChild(connector)
    presentation.appendChild(belt)
    # Lengthen the existing outgoing conveyor without inserting a second table.
    original_length=anchors(outlet)[-1][0]
    set_straight(outlet,original_length+length_out)
    blocks={field(v,"Name"):v for v in children(child(main,"EmbeddedObjects"),"EmbeddedObject")}
    for block, prop, expression in (("fromConveyorStart","sourceConveyor","loadingBelt"),
                                     ("toConveyorEnd","targetConveyor","conveyor2")):
        parameter=next(p for p in children(child(blocks[block],"Parameters"),"Parameter") if field(p,"Name")==prop)
        put(child(parameter,"Value"),"Code",expression)
    # Expose both extension lengths in the design view.
    view=next(n for n in main.getElementsByTagName("Area") if field(n,"Name")=="viewLogic")
    put(view,"X",str(int(first_x-2*radius-length_in-20)))
    put(view,"Width",str(math.ceil(last_x+length_out+20-float(field(view,"X")))))
