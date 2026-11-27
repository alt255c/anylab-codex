"""The selectable workshop recipes. Changes work on project copies."""
from pathlib import Path
import shutil
from xml.dom import minidom

from bridge.anylogic import direct, field, put
from conveyor import LineEditor, by_name
from models import child, children, load
from metro_presets import MALLS, STATIONS, add_label, apply_metro_preset

LABS = {
    "1": {"title":"Системы массового обслуживания", "templates":{}, "addons":{}, "fields":{},
          "tasks":["1.1","1.2","1.3"]},
    "2": {"title":"Цепи Маркова и надёжность", "templates":{}, "addons":{}, "fields":{},
          "tasks":["2.1","2.2"]},
    "3": {"title":"Имитационные модели", "templates":{}, "addons":{}, "fields":{},
          "tasks":["3.1","3.2","3.3"]},
    "4": {"title": "Метро", "templates": {"city": "Городской вестибюль", "contrast": "Контрастная навигация",
                                         "warm": "Тёплый камень", "cool": "Холодная отделка"},
          "addons": {"sign": "Название станции", "zones": "Цветные зоны ТЦ (4.2)", "walls": "Акцентные стены",
                     "guides": "Указатели на плане", "glass": "Тонированные витрины ТЦ (4.2)"},
          "tasks": ["4.1", "4.2"], "fields": {"station": "Свой текст вывески"},
          "choices": {"metro_station":STATIONS,"mall":MALLS}},
    "5": {"title": "Конвейер", "templates": {"classic": "Учебный цех", "smart_factory": "Современный цех",
                                           "retro_factory": "Ретро-цех", "sci_fi": "Цех в стиле научной фантастики"},
          "addons": {"wall": "Стена цеха", "transfer": "Поворотный стол (5.2)", "show_sign": "Показывать вывеску",
                     "safety": "Разметка у оборудования", "cabinet": "Шкаф инструмента", "beacons": "Сигнальные тумбы"},
          "tasks": ["5.1", "5.2"], "fields": {"sign": "Вывеска цеха"},
          "choices": {"layout": {"extended_offset": "Конвейер со смещением", "compact_straight": "Прямой конвейер", "smooth_s": "Плавный изгиб"},
                      "component": {"blue_sleeve": "Синяя втулка", "orange_sleeve": "Оранжевая втулка",
                                    "silver_spool": "Металлическая катушка", "brick": "Кирпич",
                                    "coffee": "Стаканчик кофе", "cat": "Фигурка котика"}}},
    "6": {"title": "Автозаправочная станция", "templates": {"neutral": "Базовая станция", "teal": "Бирюзовый навес",
                                                         "graphite": "Графитовый навес", "sand": "Песочная отделка"},
          "addons": {"rest": "Дополнительные лавки", "shop": "Витрины в павильоне (6.2)", "parking": "Парковка посетителей",
                     "planters": "Кашпо у зоны отдыха", "coffee": "Стойка выдачи кофе (6.2)", "show_sign": "Название АЗС на плане",
                     "fir_trees": "Ёлки на газонах"},
          "tasks": ["6.1", "6.2"], "fields": {"sign": "Название АЗС"}},
}


def rgb(value):
    return str(int(value, 16) - 2**24)


def make_models(config, directory, note):
    import anylab
    from scenarios import conveyor_scenario
    lab = config["lab"]
    station = (config["station"] or STATIONS[config["metro_station"]]) if lab=="4" else None
    plan = anylab.prepare_lab(int(lab), directory / "references", variant=config["variant"] or None,
                              student=config["student"], group=config["group"], teacher=config["teacher"] or None,
                              station=station if station!=STATIONS["generic"] else None)
    output = {}
    for task in plan["tasks"]:
        key = task["task"]
        note(f"Готовится модель {key}")
        source = Path(task["models"][0]["model"])
        if lab == "5":
            scene = {"theme": config["template"], "wall": "outside" if "wall" in config["addons"] else "none"}
            if config["sign"] and "show_sign" in config["addons"]:
                scene["sign"] = config["sign"]
            if config["colors"]:
                scene["colors"] = config["colors"]
            if key == "5.2" and "transfer" in config["addons"]:
                scene["inlet"] = "transfer_table"
            result = conveyor_scenario(source, directory / key, 12, horizon=900, seed=config["seed"],
                                       full_line=key=="5.2", layout=config["layout"],
                                       component=config["component"], scene=scene)
            output[key] = result["model"]
            decorate(Path(output[key]),key,config)
        else:
            from projects import copy_resources
            folder = directory / key
            folder.mkdir()
            copy_resources(source, folder, False)
            target = folder / f"Модель {key}.alp"
            shutil.copy2(source, target)
            decorate(target, key, config)
            output[key] = str(target)
    return output


def decorate(path, key, config):
    doc, model = load(path)
    main = by_name(child(model, "ActiveObjectClasses"), "ActiveObjectClass")["Main"]
    scene = child(main, "Presentation/Level/Presentation")
    editor = LineEditor(doc, model, main)
    addons=config["addons"]
    rectangles=by_name(scene,"Rectangle")

    def fixture(name,x,y,width,height,z,depth,tint):
        shape=editor.clone(rectangles["rectangle3"],name)
        for k,v in {"X":x,"Y":y,"Width":width,"Height":height,"Z":z,"ZHeight":depth,
                    "LineWidth":0,"FillMaterial":"null","FillColor":rgb(tint),"DrawMode":"SHAPE_DRAW_2D3D"}.items():
            put(shape,k,str(v))
        scene.appendChild(shape)

    if key.startswith("4"):
        backgrounds={"contrast":"E8F0F3","warm":"EFE3D4","cool":"DBE8EC"}
        if config["template"] in backgrounds:
            put(main,"SceneBackgroundColor",rgb(backgrounds[config["template"]]))
        if "zones" in config["addons"] and key == "4.2":
            for name, tint in (("rectangle2","E0CBB4"),("rectangle3","ECE3D1"),("glass","789C9F")):
                put(by_name(scene,"Rectangle")[name],"FillColor",rgb(tint))
        if "walls" in addons:
            for wall in main.getElementsByTagName("Wall"):
                if child(wall,"Color") is not None:
                    put(wall,"Color",rgb("668F95"))
        if "glass" in addons and key=="4.2":
            for rectangle in main.getElementsByTagName("Rectangle"):
                if field(rectangle,"Name").startswith("glass"):
                    put(rectangle,"FillMaterial","null")
                    put(rectangle,"FillColor",rgb("83AEB6"))
        apply_metro_preset(main,key,config,editor,Path(__file__).parent,path.parent)
        if "guides" in addons:
            add_label(scene,editor,Path(__file__).parent,"anylabGateGuide",490,780,"ДОСМОТР")
            add_label(scene,editor,Path(__file__).parent,"anylabEntryGuide",750,1050,"ТУРНИКЕТЫ")
        configure_metro_grid(model,key)
    elif key.startswith("5"):
        if "safety" in addons:
            for i in range(8):
                fixture(f"anylabSafety{i}",263+32*i,307,18,3,1,.2,"E7BB5C")
        if "cabinet" in addons:
            fixture("anylabToolCabinet",530,21,38,15,0,22,"365A62")
            fixture("anylabToolCounter",529,20,40,17,22,2,"ADC2BE")
        if "beacons" in addons:
            for i,x in enumerate((192,602)):
                fixture(f"anylabBeaconPost{i}",x,28,4,4,0,15,"39484D")
                fixture(f"anylabBeacon{i}",x-1,27,6,6,15,3,"E8AE50")
    else:
        from station_layout import fix_station_layout
        fix_station_layout(doc,model,main)
        palettes={"teal":("278579","254F54"),"graphite":("47565D","293A44"),"sand":("D9CCAA","82785F")}
        if config["template"] in palettes:
            for name,tint in zip(("rectangle23","rectangle4"),palettes[config["template"]]):
                put(rectangles[name],"FillColor",rgb(tint))
                put(rectangles[name],"FillMaterial","null")

        for name,shape in rectangles.items():
            color=""
            if name in {"rectangle23","крышаНадКассами"}:
                color=config["colors"].get("station_roof")
            elif name in {"rectangle4","СтенаПавильона","СевернаяСтена","ЮжнаяСтена"}:
                color=config["colors"].get("station_walls")
            elif name.startswith(("фасцияНавеса","опораНавеса","торецНавеса","стойкаКрыши","торецКрышиКасс")):
                color=config["colors"].get("station_trim")
            if color:
                put(shape,"FillMaterial","null")
                put(shape,"FillColor",rgb(color[1:]))

        if "rest" in config["addons"]:
            fixture("anylabRestPad",105,520,82,66,0,1,"A5B3A8")
            for i,y in enumerate((532,561)):
                fixture(f"anylabBenchBase{i}",114,y,34,6,1,4,"405851")
                fixture(f"anylabBench{i}",114,y,34,6,5,1.5,"BB996C")
        if "shop" in config["addons"] and key == "6.2":
            for i,y in enumerate((344,389,430)):
                fixture(f"anylabShelf{i}",318,y,7,8,1.1,8,"385B52")
                fixture(f"anylabDisplay{i}",318,y,7,8,9.1,3,"D3B491")
        if "parking" in addons:
            fixture("anylabParking",10,584,116,53,0,.1,"424F54")
            for i in range(5):
                fixture(f"anylabParkingLine{i}",17+24*i,592,1.5,35,.12,.08,"E4E2C9")
        if "planters" in addons:
            for i,y in enumerate((422,453,484)):
                fixture(f"anylabPlanter{i}",12,y,8,8,.7,4,"826A55")
                fixture(f"anylabPlant{i}",13,y+1,6,6,4.7,4,"668B69")
        if "coffee" in addons and key=="6.2":
            fixture("anylabCoffeeCounter",297,460,11,7,1,8,"43645B")
            fixture("anylabCupStack",301,462,3,3,9,3,"E3CFAD")
        if "show_sign" in addons and config["sign"]:
            put(by_name(scene,"Text")["labTheme"],"Text",config["sign"])
        if "fir_trees" in addons:
            add_fir_trees(path, doc, model, scene, editor)
        author=by_name(scene,"Text").get("labAuthor")
        if author is not None:
            put(author,"Text",f"{config['student']} · {config['group']} · ЛР{key}")
    path.write_bytes(doc.toxml(encoding="utf-8"))


def add_fir_trees(path,doc,model,scene,editor):
    templates=Path(__file__).with_name("templates")
    prototype=minidom.parse(str(templates/"presentation"/"station-tree.xml")).documentElement
    mesh="3d/tree_1.dae"
    resources=child(model,"ModelResources")
    if not any(field(entry,"Path")==mesh for entry in children(resources,"Resource")):
        entry=resources.appendChild(doc.createElement("Resource"))
        put(entry,"Id",str(editor.next_id))
        editor.next_id+=1
        put(entry,"Path",mesh)
        put(entry,"ReferencedFromUserCode","false")
        put(entry,"Location","FILE_SYSTEM")
    target=path.parent/mesh
    if not target.is_file():
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(templates/"models"/"6.2"/"1"/mesh,target)

    for index,(x,y,scale) in enumerate(((48,236,.45),(92,312,.55),(53,364,.42),(774,241,.46),(835,251,.51))):
        shape=editor.clone(prototype,f"anylabFirTree{index}")
        for axis,coordinate in (("X",x),("Y",y)):
            for position in direct(shape,axis):
                position.firstChild.data=str(coordinate)
        put(shape,"Scale",str(scale))
        put(child(shape,"ResourceReference"),"PackageName",field(model,"JavaPackageName"))
        scene.appendChild(shape)


def configure_metro_grid(model,key):
    for experiment in children(child(model,"Experiments"),"ParamVariationExperiment"):
        for row in children(experiment,"RangeVariationParamValue"):
            if field(row,"Type")!="RANGE":
                continue
            start=field(child(row,"From"),"Code")
            if key=="4.1":
                values=(100,900,200)
            elif start in {"100","100.0","150"}:
                values=(150,750,300)
            else:
                continue
            for tag,value in zip(("From","To","Step"),values):
                put(child(row,tag),"Code",str(value))
