"""Architectural presets for the two educational pedestrian models."""

from bridge.anylogic import field, put
from conveyor import by_name
from models import child, children, load
from metro_operations import add_boarding, camera_panel
from metro_layout import LAYOUTS, draw_plan, install_layout


STATIONS = {
    "generic": "Учебная станция",
    "kantemirovskaya": "Кантемировская",
    "tsaritsyno": "Царицыно",
    "kashirskaya": "Каширская",
    "klenovy_bulvar": "Кленовый бульвар",
    "kolomenskaya": "Коломенская",
    "nagatinsky_zaton": "Нагатинский Затон",
}

# Wall, contrasting material, light, and layout of the architectural elements.
STATION_STYLES = {
    "kantemirovskaya": ("A09883", "744737", "F1D3A1", "ribs"),
    "tsaritsyno": ("DBD6C5", "805D57", "E9BF85", "panels"),
    "kashirskaya": ("BEBCC1", "485867", "E0E8ED", "paired"),
    "klenovy_bulvar": ("D7C4A7", "93694F", "FFF4DC", "vault"),
    "kolomenskaya": ("E0D9B8", "667D56", "E6E7CA", "longitudinal"),
    "nagatinsky_zaton": ("BAC3C8", "365962", "D7EFF4", "mosaic"),
}

MALLS = {
    "atrium": "ТЦ «Атриум» · центральная галерея",
    "market": "ТЦ «Рынок» · ряды павильонов",
    "food_hall": "ТЦ «Фуд-холл» · площадка со столиками",
    "winter_garden": "ТЦ «Зимний сад» · озеленённый двор",
}

MALL_PALETTES = {
    "atrium": ("D7D9D7", "98B5BC", "3D6874"),
    "market": ("E5D4BC", "BC975C", "783F2F"),
    "food_hall": ("E8DABD", "E2AA56", "6A4439"),
    "winter_garden": ("D2DBD0", "9CBFB0", "355F52"),
}


def caption_plan(doc, folder, name, station, accent, layout):
    """Install the station-specific plan as the native AnyLogic floor resource."""
    from PIL import Image, ImageDraw, ImageFont

    path=folder/"subway_Kantemirovskaya_scheme.png"
    if layout:
        plan=draw_plan(layout,name,"#"+(accent or "215D56"))
    else:
        with Image.open(path) as image:
            plan=image.convert("RGB")
        label_base_plan(plan,name,station,accent,ImageDraw,ImageFont)
    filename=f"metro_plan_{station}.png"
    plan.save(folder/filename)
    for tag in ("ClassName","Path"):
        for token in doc.getElementsByTagName(tag):
            if token.firstChild and token.firstChild.data==path.name:
                token.firstChild.data=filename
    path.unlink()


def label_base_plan(plan,name,station,accent,ImageDraw,ImageFont):
    draw=ImageDraw.Draw(plan)
    scale=plan.width/1000
    def points(*values):
        return tuple(round(v*scale) for v in values)
    for box in ((145,8,240,44),(696,10,794,48),(293,124,427,147),
                (418,204,618,235),(613,288,728,310)):
        draw.rectangle(points(*box),fill="white")
    if accent:
        draw.rectangle(points(297,151,730,177),fill="#"+accent)
        draw.rectangle(points(297,258,730,283),fill="#"+accent)
    try:
        title=ImageFont.truetype("DejaVuSans.ttf",round(20*scale))
    except OSError:
        title=ImageFont.truetype("arial.ttf",round(20*scale))
    small=title.font_variant(size=round(14*scale))
    if title.getlength(name)>410*scale:
        title=title.font_variant(size=max(8,int(title.size*410*scale/title.getlength(name))))
    draw.text(points(516,220),name,font=title,fill="#174e3c",anchor="mm")
    labels=("← Каширская","Царицыно →") if station=="kantemirovskaya" else ("← Путь 1","Путь 2 →")
    for coordinate,label in zip(((296,136),(618,297),(150,24),(702,26)),
                                (*labels,"Вестибюль 1","Вестибюль 2")):
        draw.text(points(*coordinate),label,font=small,fill="#174e3c",anchor="lm")


def apply_metro_preset(main, part, config, editor, runtime, model_folder):
    levels = children(child(main, "Presentation"), "Level")
    scene = child(levels[0], "Presentation")
    station = config["metro_station"]
    mall = config["mall"]
    station_label = config["station"] or STATIONS[station]
    show_name = station != "generic" or bool(config["station"]) or "sign" in config["addons"]
    colors={key:value[1:] for key,value in config["colors"].items()}
    _, reference = load(runtime / "templates/models/4.2/1/Model.alp")
    reference_main = by_name(child(reference,"ActiveObjectClasses"), "ActiveObjectClass")["Main"]
    tile = by_name(child(reference_main,"Presentation/Level/Presentation"), "Rectangle")["rectangle4"]
    opaque="glass" not in config["addons"]
    camera_panel(main,scene,part,editor,reference_main,opaque)
    layout=install_layout(scene,editor,station) if station in LAYOUTS else None
    for wall in children(scene,"Wall"):
        name=field(wall,"Name")
        put(wall,"ZHeight","34" if name.startswith("metroPassageWall") or name in
            {"wall","wall1","wall2","wall3","wall4","wall5"} else "27")
    add_boarding(scene,editor,side_platforms=bool(layout and layout[0]=="side"))
    caption_plan(editor.doc,model_folder,station_label,station,colors.get("metro_accent"),layout)

    def color(value):
        return str(int(value, 16)-2**24)

    def solid(name, x, y, width, height, z, depth, tint, mode="SHAPE_DRAW_3D"):
        shape = editor.clone(tile, name)
        for k,v in {"X":x,"Y":y,"Z":z,"Width":width,"Height":height,"ZHeight":depth,
                    "LineWidth":0,"FillMaterial":"null","FillColor":color(tint),"DrawMode":mode}.items():
            put(shape,k,str(v))
        scene.appendChild(shape)

    if station in STATION_STYLES or "metro_walls" in colors:
        wall=colors.get("metro_walls",STATION_STYLES.get(station,("A09883",))[0])
        for item in children(scene,"Wall"):
            put(item,"LineColor",color(wall))
            put(item,"LineMaterial","null")

    if station in STATION_STYLES:
        _, accent, light, design = STATION_STYLES[station]
        accent=colors.get("metro_accent",accent)
        # Anchor the accents to the floor of the actual platform type.
        platforms={"side":(890,1205),"interchange":(806,1304),"island":(1018,1080)}
        lanes=platforms[layout[0] if layout else "island"]
        if design=="longitudinal":
            for i,y in enumerate(lanes):
                solid(f"metroFloorInlay{i}",1140,y,1560,5,.10,.06,accent)
        else:
            spacing={"ribs":225,"vault":180,"paired":240,"panels":215,"mosaic":134}[design]
            for i,x in enumerate(range(1150,2750,spacing)):
                for j,y in enumerate(lanes):
                    solid(f"metroFloorInlay{i}_{j}",x,y,24 if design=="mosaic" else 45,5,
                          .10,.06,light if (i+j)%2 else accent)

    if show_name:
        add_label(scene,editor,runtime,"metroNameLeft",310,755,station_label)
        add_label(scene,editor,runtime,"metroNameRight",3080,750,station_label)

    if part != "4.2":
        return
    floor, glass, trim = MALL_PALETTES[mall]
    if "zones" in config["addons"]:
        floor="ECE3D1"
    if "glass" in config["addons"]:
        glass="83AEB6"
    floor=colors.get("mall_floor",floor)
    glass=colors.get("mall_facade",glass)
    for level in levels:
        for shape in children(child(level,"Presentation"),"Rectangle"):
            name=field(shape,"Name")
            if name.startswith("glass"):
                put(shape,"FillColor",color(glass) if opaque else str(int("92"+glass,16)-2**32))
                put(shape,"FillMaterial","null")
            elif name.startswith("rectangle") and name[9:].isdigit():
                put(shape,"FillColor",color(trim if name in {"rectangle4","rectangle5","rectangle6","rectangle7"} else floor))
    # The apron is outside the building footprint. Leave the center and its approaches open.
    if mall == "atrium":
        for i,x in enumerate((3190,3490,3790)):
            solid(f"mallCanopy{i}",x,-555,136,26,23,3,trim)
        for i,x in enumerate((3250,3710)):
            solid(f"mallDirectory{i}",x,-84,65,8,1,23,trim,"SHAPE_DRAW_2D3D")
    elif mall == "market":
        for i,x in enumerate((3185,3285,3650,3750)):
            solid(f"mallStall{i}",x,-597,64,37,0,13,trim,"SHAPE_DRAW_2D3D")
            solid(f"mallAwning{i}",x-3,-601,70,45,23,3,glass)
            solid(f"mallCounter{i}",x,-100,56,12,0,9,glass,"SHAPE_DRAW_2D3D")
    elif mall == "food_hall":
        for i,x in enumerate((3170,3250,3720,3800)):
            solid(f"mallTable{i}",x,-37,34,20,7,2,trim,"SHAPE_DRAW_2D3D")
            for j,y in enumerate((-47,-13)):
                solid(f"mallSeat{i}_{j}",x+4,y,26,7,3,3,glass,"SHAPE_DRAW_2D3D")
        for i,x in enumerate((3220,3710)):
            solid(f"mallFoodCounter{i}",x,-83,95,15,0,12,trim,"SHAPE_DRAW_2D3D")
    else:
        for i,(x,y) in enumerate(((3185,-600),(3285,-600),(3675,-600),(3775,-600))):
            solid(f"mallPlanter{i}",x,y,68,33,0,7,trim,"SHAPE_DRAW_2D3D")
            solid(f"mallHedge{i}",x+4,y+4,60,25,7,7,"689470","SHAPE_DRAW_2D3D")
        for i,x in enumerate((3180,3300,3710,3810)):
            solid(f"mallIndoorPlanter{i}",x,-85,49,16,0,6,trim,"SHAPE_DRAW_2D3D")
            solid(f"mallIndoorHedge{i}",x+4,-82,41,10,6,10,"689470","SHAPE_DRAW_2D3D")
    add_label(scene,editor,runtime,"metroMallName",3190,-675,MALLS[mall].split(" · ")[0])


def add_label(scene,editor,runtime,name,x,y,label):
    _, reference=load(runtime / "templates/models/6.1/1/Model.alp")
    main=by_name(child(reference,"ActiveObjectClasses"),"ActiveObjectClass")["Main"]
    prototype=children(child(main,"Presentation/Level/Presentation"),"Text")[0]
    text=editor.clone(prototype,name)
    for key,value in {"X":x,"Y":y,"Z":0,"Text":label,"TextCode":"","DrawMode":"SHAPE_DRAW_2D",
                      "Color":str(int("273846",16)-2**24),"ShowLabel":"false","OnClickCode":""}.items():
        put(text,key,str(value))
    put(child(text,"Font"),"Size","22")
    scene.appendChild(text)
