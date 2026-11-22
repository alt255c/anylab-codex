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


def conveyor_scenario(source, destination, rate, horizon=600, seed=1, full_line=False):
    """Build the lab's finite measurement profile and optional loading/unloading line."""
    from projects import copy_resources, new_directory
    if any(isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or n<=0
           for n in (rate,horizon)):
        raise ValueError("Интенсивность и горизонт должны быть положительными")
    if type(seed) is not int or not 0<=seed<=2147483647:
        raise ValueError("Зерно должно быть целым числом от 0 до 2147483647")
    path = Path(source).resolve(strict=True)
    doc, model = load(path)
    main = next((a for a in children(child(model,"ActiveObjectClasses"),"ActiveObjectClass")
                 if field(a,"Name")=="Main"), None)
    if main is None:
        raise ValueError("Выберите встроенный шаблон средней части конвейера ЛР5")
    parameter = next((p for p in children(child(main,"Variables"),"Variable")
                      if field(p,"Name")=="ИнтенсивностьПрибытия"), None)
    network = next(iter(main.getElementsByTagName("ConveyorNetwork")),None)
    if parameter is None or network is None:
        raise ValueError("Выберите встроенный шаблон средней части конвейера ЛР5")
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
        add_terminal_sections(doc,main,network)
        from conveyor import extend_line
        assets = extend_line(doc, model, main, network)
    dest=Path(destination).resolve()
    with new_directory(dest) as stage:
        copy_resources(path,stage,False)
        for resource in assets:
            relative = Path("3d") / resource.name
            (stage / relative.parent).mkdir(exist_ok=True)
            shutil.copy2(resource, stage / relative)
        (stage/(name+".alp")).write_bytes(doc.toxml(encoding="UTF-8"))
    return dict(model=str(dest/(name+".alp")), rate_per_minute=rate, horizon_seconds=horizon,
                seed=seed, full_line=full_line, experiment=field(experiment,"Name"))


def add_terminal_sections(doc, main, network):
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
    length_in,length_out=144,166
    first_x=float(field(inlet,"X"))
    last_x=float(field(outlet,"X"))+anchors(outlet)[-1][0]
    for original, name, table_x, start, length, inbound in (
        (inlet,"loadingBelt",first_x-radius,first_x-2*radius-length_in,length_in,True),
        (outlet,"unloadingBelt",last_x+radius,last_x+2*radius,length_out,False)):
        connector=clone(turntable,"loadingTransfer" if inbound else "unloadingTransfer")
        put(connector,"X",str(table_x));put(connector,"Y",y)
        belt=clone(original,name)
        # Positions/sensors follow the original segment.
        for section in children(belt,"Presentation"):
            belt.removeChild(section)
        for side in ("SourceId","TargetId"):
            if belt.hasAttribute(side):belt.removeAttribute(side)
        ident=field(connector,"Id")
        belt.setAttribute("TargetId" if inbound else "SourceId",ident)
        original.setAttribute("SourceId" if inbound else "TargetId",ident)
        put(belt,"X",str(start));put(belt,"Y",y);set_straight(belt,length)
        presentation.appendChild(connector)
        presentation.appendChild(belt)
    blocks={field(v,"Name"):v for v in children(child(main,"EmbeddedObjects"),"EmbeddedObject")}
    for block, prop, expression in (("fromConveyorStart","sourceConveyor","loadingBelt"),
                                     ("toConveyorEnd","targetConveyor","unloadingBelt")):
        parameter=next(p for p in children(child(blocks[block],"Parameters"),"Parameter") if field(p,"Name")==prop)
        put(child(parameter,"Value"),"Code",expression)
    # Expose both extension lengths in the design view.
    view=next(n for n in main.getElementsByTagName("Area") if field(n,"Name")=="viewLogic")
    put(view,"X",str(int(first_x-2*radius-length_in-20)))
    put(view,"Width",str(math.ceil(last_x+2*radius+length_out+20-float(field(view,"X")))))
