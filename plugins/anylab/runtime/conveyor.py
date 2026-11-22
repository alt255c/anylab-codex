"""Extend the LR5 packing template using the installed conveyor tutorials."""
from pathlib import Path

from bridge.anylogic import field, put
from models import anchors, child, children, load, route_curve, set_points


def by_name(parent, tag):
    return {field(node, "Name"): node for node in children(parent, tag)}


def set_param(block, name, value):
    parameter = by_name(child(block, "Parameters"), "Parameter")[name]
    item = child(parameter, "Value")
    if item is None:
        item = parameter.appendChild(parameter.ownerDocument.createElement("Value"))
        item.setAttribute("Class", "CodeValue")
    put(item, "Code", value)


class LineEditor:
    def __init__(self, doc, model, main):
        self.doc = doc
        self.model = model
        self.main = main
        self.package = field(model, "JavaPackageName")
        self.next_id = max(int(n.firstChild.data) for n in doc.getElementsByTagName("Id")
                           if n.firstChild and n.firstChild.data.isdecimal()) + 1
        self.embedded = child(main, "EmbeddedObjects")
        self.blocks = by_name(self.embedded, "EmbeddedObject")
        self.connectors = child(main, "Connectors")
        self.connector = children(self.connectors, "Connector")[0]

    def clone(self, original, name=None, imported_package=None):
        item = self.doc.importNode(original, True)
        if name is not None:
            put(item, "Name", name)
        ids = {}
        for token in item.getElementsByTagName("Id"):
            if token.firstChild and token.firstChild.data.isdecimal():
                ids[token.firstChild.data] = str(self.next_id)
                token.firstChild.data = str(self.next_id)
                self.next_id += 1
        for node in [item, *item.getElementsByTagName("*")]:
            for key in ("SourceId", "TargetId"):
                value = node.getAttribute(key)
                if value in ids:
                    node.setAttribute(key, ids[value])
            if node.tagName in {"CurrentLevel", "ItemName"} and node.firstChild:
                value = node.firstChild.data
                node.firstChild.data = ids.get(value, value)
            if imported_package and node.tagName == "PackageName" and node.firstChild:
                if node.firstChild.data == imported_package:
                    node.firstChild.data = self.package
        return item

    def block(self, original, name, x, y, params=None, package=None):
        node = self.clone(original, name, package)
        place(node, x, y)
        for key, value in (params or {}).items():
            set_param(node, key, value)
        self.embedded.appendChild(node)
        self.blocks[name] = node
        return node

    def connect(self, source, target, start, end, bends=(), target_port="in"):
        node = self.clone(self.connector, "link" + str(self.next_id))
        points = []
        for name, prefix, offset, port in ((source, "Source", start, "out"),
                                           (target, "Target", end, target_port)):
            block = self.blocks[name]
            ref = child(node, prefix + "EmbeddedObjectReference")
            put(ref, "ItemName", name)
            ref = child(node, prefix + "ConnectableItemReference")
            definition = child(block, "ActiveObjectClass")
            put(ref, "PackageName", field(definition, "PackageName"))
            put(ref, "ClassName", field(definition, "ClassName"))
            put(ref, "ItemName", port)
            points.append((int(field(block, "X")) + offset[0], int(field(block, "Y")) + offset[1]))
        origin = points[0]
        place(node, *origin)
        sequence = child(node, "Points")
        for item in children(sequence, "Point"):
            sequence.removeChild(item)
        for x, y in (origin, *bends, points[1]):
            point = sequence.appendChild(self.doc.createElement("Point"))
            place(point, x-origin[0], y-origin[1])
        self.connectors.appendChild(node)

    def unlink(self, source, target):
        for node in children(self.connectors, "Connector"):
            ends = [field(child(node, k+"EmbeddedObjectReference"), "ItemName") for k in ("Source", "Target")]
            if ends == [source, target]:
                self.connectors.removeChild(node)
                return
        raise ValueError(f"В шаблоне нет соединения {source} → {target}")

    def variable(self, agent, prototype, name, initial, y, value_type="boolean"):
        node = self.clone(prototype,name)
        place(node, 100, y)
        put(child(node,"Properties"), "Type", value_type)
        put(child(node,"Properties/InitialValue"), "Code", initial)
        child(agent,"Variables").appendChild(node)

    def caption(self, name, label, x, y):
        level = child(self.main, "Presentation/Level/Presentation")
        prototype = next(t for t in level.getElementsByTagName("Text") if field(t,"Name") == "text")
        node = self.clone(prototype, name)
        place(node, x, y)
        put(node, "Text", label)
        put(node, "Color", "-14671840")
        level.appendChild(node)


def place(node, x, y):
    put(node, "X", str(x))
    put(node, "Y", str(y))


def argb(hex_color):
    value=int(hex_color.lstrip("#"),16) | 0xFF000000
    return value-0x100000000 if value >= 0x80000000 else value


def tutorial(name):
    from anylab import examples
    files = [Path(p) for p in examples(name) if Path(p).stem == name]
    if not files:
        raise FileNotFoundError(f"Установите учебный пример AnyLogic {name}")
    _, model = load(files[0])
    return files[0], model, child(model,"ActiveObjectClasses/ActiveObjectClass")


def build_loading(editor, network, enter_model, enter_main):
    model = editor.model
    carton = by_name(child(model,"ActiveObjectClasses"),"ActiveObjectClass")["Carton"]
    flag = by_name(child(carton,"Variables"),"Variable")["isSealed"]
    for index, name in enumerate(("hasPalletSheet","hasAssemblyPart","isComponent")):
        editor.variable(carton,flag,name,"false",200+50*index)
    for index, name in enumerate(("ordinaryDelivered","fragileDelivered","manualDelivered","assembled")):
        editor.variable(editor.main,flag,name,"0",820+50*index,"int")

    belt_shapes = child(network,"Presentation")
    available_belts=by_name(belt_shapes,"Conveyor")
    inlet=available_belts.get("loadingBelt",available_belts.get("conveyor"))
    if inlet is None:
        raise ValueError("В модели не найден основной конвейер для точки слияния")
    part = editor.clone(inlet,"partFeeder")
    part.removeAttribute("TargetId")
    join_x = round(float(field(inlet,"X"))+82)
    join_y = round(float(field(inlet,"Y")))
    feeder_start_y=join_y-180
    feeder_extension=25
    feeder_length=180+feeder_extension
    feeder_end_y=join_y+feeder_extension
    place(part,join_x,feeder_start_y)
    set_points(part,route_curve([(0,0,0),(0,feeder_length,0)]))
    # Convey requires real PositionOnConveyor descriptors for both ends.
    position_proto = next((n for n in children(inlet,"PositionOnConveyor")), None)
    if position_proto is None:
        position_proto = next(iter(network.getElementsByTagName("PositionOnConveyor")), None)
    if position_proto is None:
        raise ValueError("В шаблоне конвейера отсутствуют точки позиционирования")
    part_presentation=child(part,"Presentation")
    if part_presentation is None:
        part_presentation=part.appendChild(editor.doc.createElement("Presentation"))
    else:
        # The cloned straight belt carries two template sensor/controller names.
        # Keep only the newly named positions to prevent duplicate Java methods.
        while part_presentation.firstChild:
            part_presentation.removeChild(part_presentation.firstChild)
    for name, y in (("partStart",feeder_start_y),("partJoin",feeder_end_y)):
        descriptor = editor.clone(position_proto,name)
        place(descriptor,join_x,y)
        part_presentation.appendChild(descriptor)
    belt_shapes.appendChild(part)
    editor.caption("loadingText","Подача детали ↓",int(join_x)-72,int(join_y)-176)

    package = field(enter_model,"JavaPackageName")
    blocks = by_name(child(enter_main,"EmbeddedObjects"),"EmbeddedObject")
    source, manual, convey = (editor.blocks[k] for k in ("source","source1","fromConveyorStart"))
    place(source,-455,400)
    editor.block(manual,"sheetSource",-455,520,{"onAtExit":"agent.isComponent = true;"})
    editor.block(manual,"partSource",join_x-18,feeder_start_y-12,{"onAtExit":"agent.isComponent = true;"})
    # Inject exactly one part and one sheet for each pallet.
    set_param(source,"onAtExit","sheetSource.inject(1); partSource.inject(1);")
    set_param(source,"locationX",str(float(field(inlet,"X"))))
    set_param(source,"locationY",str(join_y))
    travel = editor.block(convey,"partTravel",-270,580,{
        "sourceConveyor":"partFeeder","targetConveyor":"partFeeder",
        "sourceType":"self.SOURCE_POSITION_ON_CONVEYOR","sourcePositionOnConveyor":"partStart",
        "targetType":"self.TARGET_POSITION_ON_CONVEYOR","targetPositionOnConveyor":"partJoin",
    })
    set_param(editor.blocks["partSource"],"locationX",str(join_x))
    set_param(editor.blocks["partSource"],"locationY",str(feeder_start_y))
    fit_sheet = editor.block(blocks["addSheet"],"fitSheet",-270,400,{
        "onExit":"((Carton)agent).hasPalletSheet = true;"
    },package)
    fit_part = editor.block(blocks["addSheet"],"fitPart",-95,400,{
        "onExit":"((Carton)agent).hasAssemblyPart = true; assembled++;"
    },package)
    for block in (fit_sheet,fit_part):
        for generic in children(block,"GenericParameterSubstitute"):
            value = child(generic,"GenericParameterSubstituteValue")
            if value is not None:
                put(value,"Code","Carton")
    editor.unlink("source","fromConveyorStart")
    editor.connect("source","fitSheet",(30,10),(10,10),target_port="in1")
    editor.connect("sheetSource","fitSheet",(30,10),(10,30),((-315,530),(-315,430)),target_port="in2")
    editor.connect("fitSheet","fitPart",(30,10),(10,10),target_port="in1")
    editor.connect("partSource","partTravel",(30,10),(0,10))
    editor.connect("partTravel","fitPart",(40,10),(10,30),((-150,590),(-150,430)),target_port="in2")
    editor.connect("fitPart","fromConveyorStart",(30,10),(0,10))

    # A small share enters the hand-assembly route during measurement as well.
    set_param(manual,"arrivalType","self.RATE")
    set_param(manual,"rate","ИнтенсивностьПрибытия * 0.12")
    rate = by_name(child(source,"Parameters"),"Parameter")["rate"]
    manual_rate = by_name(child(manual,"Parameters"),"Parameter")["rate"]
    manual_rate.replaceChild(editor.doc.importNode(child(rate,"Value"),True),child(manual_rate,"Value"))
    set_param(manual,"rate","ИнтенсивностьПрибытия * 0.12")
    set_param(manual,"onAtExit","agent.isManuallyAdded = true; agent.isFragile = false;")

    # Reuse the tutorial's pallet geometry and its thin anti-slip sheet.
    pallet = by_name(child(enter_model,"ActiveObjectClasses"),"ActiveObjectClass")["Pallet"]
    src = child(pallet,"Shapes")
    dest = child(carton,"Presentation/Level/Presentation")
    assets = []
    for shape in children(src):
        if shape.tagName not in {"Figure3D","Rectangle","Group"}:
            continue
        duplicate = editor.clone(shape,"assembly"+field(shape,"Name"),package)
        visibility = field(shape,"VisibleCode")
        if visibility:
            visibility = visibility.replace("coveredWithSheet","hasPalletSheet")
        put(duplicate,"VisibleCode","!isComponent && !isManuallyAdded" +
            (" && ("+visibility+")" if visibility else ""))
        # Imported 3D meshes have no 2D bitmap preview. AnyLogic draws a
        # broken-image placeholder when these are set to 2D+3D, so keep the
        # meshes in the 3D view and provide explicit vector proxies below.
        if duplicate.tagName == "Figure3D":
            put(duplicate,"DrawMode","SHAPE_DRAW_3D")
        dest.appendChild(duplicate)
        assets.extend(n.firstChild.data for n in duplicate.getElementsByTagName("ClassName")
                      if n.firstChild and n.firstChild.data.startswith("3d/"))
    # Replace the inherited bottle/pipe illustration with an original,
    # purpose-built sleeve mesh. The same component is visible on its feeder
    # and after it has been added to an open carton.
    for old in list(children(dest)):
        if field(old,"Name") in {"pipe_corner","bottle_6","fragileStamp"}:
            dest.removeChild(old)
    proto = next((s for s in children(dest,"Figure3D") if field(s,"Name")=="box_1_open"),None)
    if proto is not None:
        sleeve = editor.clone(proto,"blueSleeve")
        put(sleeve,"DrawMode","SHAPE_DRAW_3D")
        class_name=child(sleeve,"ResourceReference/ClassName")
        while class_name.firstChild:
            class_name.removeChild(class_name.firstChild)
        class_name.appendChild(editor.doc.createCDATASection("3d/blue_sleeve.dae"))
        x_nodes=children(sleeve,"X"); y_nodes=children(sleeve,"Y")
        for node in (*x_nodes,*y_nodes):
            put(sleeve,node.tagName,"0")
        z_nodes=children(sleeve,"Z")
        if z_nodes: put(sleeve,"Z","0")
        put(sleeve,"VisibleCode","isComponent || (!isSealed && hasAssemblyPart && !isManuallyAdded)")
        dest.appendChild(sleeve)
        # In 2D, represent the cylindrical part as a blue disc instead of
        # allowing AnyLogic's generic green agent marker to show through.
        disc=next((s for s in children(dest,"Rectangle") if field(s,"Name")=="assemblyrectangle"),None)
        if disc is not None:
            icon=editor.clone(disc,"blueSleeve2D")
            place(icon,-9,-9)
            put(icon,"Width","18"); put(icon,"Height","18")
            put(icon,"Z","9"); put(icon,"FillColor",str(-15092048))
            put(icon,"DrawMode","SHAPE_DRAW_2D")
            put(icon,"VisibleCode","isComponent || (!isSealed && hasAssemblyPart && !isManuallyAdded)")
            dest.appendChild(icon)
            # Give cartons a clean vector appearance in the 2D view instead
            # of relying on the missing preview of the imported 3D box mesh.
            box=editor.clone(disc,"carton2D")
            place(box,-20,-20)
            put(box,"Width","40"); put(box,"Height","40")
            put(box,"Z","8"); put(box,"FillColor",str(argb("#19B6B0")))
            put(box,"DrawMode","SHAPE_DRAW_2D")
            put(box,"VisibleCode","!isComponent")
            dest.appendChild(box)
            tape=editor.clone(disc,"cartonTape2D")
            place(tape,-5,-20)
            put(tape,"Width","10"); put(tape,"Height","40")
            put(tape,"Z","9"); put(tape,"FillColor",str(argb("#F28A3C")))
            put(tape,"DrawMode","SHAPE_DRAW_2D")
            put(tape,"VisibleCode","!isComponent")
            dest.appendChild(tape)
    return assets


def extend_loading(doc,model,main,network):
    """Add the perpendicular component feeder to the standalone middle section."""
    if ("partFeeder" in by_name(child(network,"Presentation"),"Conveyor") and
            {"partSource","partTravel","fitPart"}.issubset(by_name(child(main,"EmbeddedObjects"),"EmbeddedObject"))):
        _normalize_feeder(LineEditor(doc,model,main),network,main)
        return []
    editor=LineEditor(doc,model,main)
    enter,enter_model,enter_main=tutorial("ConveyorEnter")
    assets=build_loading(editor,network,enter_model,enter_main)
    resources=child(model,"ModelResources")
    known={field(r,"Path") for r in children(resources,"Resource")}
    paths=[]
    for name in sorted(set(assets)):
        if name in known:
            continue
        resource=next(r for r in children(child(enter_model,"ModelResources"),"Resource")
                      if field(r,"Path")==name)
        resources.appendChild(editor.clone(resource))
        paths.append(enter.parent/name)
        known.add(name)
    return paths


def build_shipping(editor, network, exit_model, exit_main):
    package = field(exit_model,"JavaPackageName")
    blocks = by_name(child(exit_main,"EmbeddedObjects"),"EmbeddedObject")
    forklift = by_name(child(exit_model,"ActiveObjectClasses"), "ActiveObjectClass")["Forklift"]
    child(editor.model,"ActiveObjectClasses").appendChild(editor.clone(forklift,imported_package=package))

    belt = by_name(child(network,"Presentation"),"Conveyor")["conveyor2"]
    exit_x = round(float(field(belt,"X"))+anchors(belt)[-1][0])
    exit_y = round(float(field(belt,"Y")))
    terminal = child(exit_main,"Presentation/Level/Presentation")
    original = children(terminal,"Network")[0]
    paths = editor.clone(original,"warehouseNetwork",package)
    put(paths,"DrawMode","SHAPE_DRAW_2D3D")
    space = child(paths,"Presentation")
    store = by_name(space,"RectangleNode")["storage"]
    point = by_name(space,"PointNode")["node1"]
    outbound = next(n for n in children(space,"Path") if n.getAttribute("TargetId")==field(store,"Id"))

    dx,dy = exit_x-int(field(original,"X")),exit_y-int(field(original,"Y"))
    for element in [paths,*children(space),*space.getElementsByTagName("Attractor")]:
        place(element,int(field(element,"X"))+dx,int(field(element,"Y"))+dy)
    put(store,"Name","ordinaryWarehouse")
    put(store,"Width","170")
    put(store,"Height","112")
    for name, delta, label in (("fragileWarehouse",-245,"Хрупкие"),("manualWarehouse",245,"Ручная сборка")):
        node=editor.clone(store,name)
        x,y=int(field(store,"X")),int(field(store,"Y"))+delta
        place(node,x,y)
        for attr in node.getElementsByTagName("Attractor"):
            put(attr,"Name",name+field(attr,"Name").title())
            place(attr,int(field(attr,"X")),int(field(attr,"Y"))+delta)
        road=editor.clone(outbound,"path"+name.title())
        road.setAttribute("TargetId",field(node,"Id"))
        sx,sy=int(field(point,"X")),int(field(point,"Y"))
        place(road,sx,sy)
        set_points(road,route_curve([(0,0,0),(x+36-sx,y+36-sy,0)]))
        space.appendChild(node)
        space.appendChild(road)
        editor.caption(name+"Label",label,x+10,y+18)
    editor.caption("ordinaryWarehouseLabel","Обычные",int(field(store,"X"))+10,int(field(store,"Y"))+18)
    child(editor.main,"Presentation/Level/Presentation").appendChild(paths)

    editor.unlink("toConveyorEnd","sink")
    set_param(editor.blocks["toConveyorEnd"],"removeFromConveyor","false")
    homes=["forkliftHome"]
    home_x,home_y=int(field(point,"X")),int(field(point,"Y"))
    for index,(dx,dy) in enumerate(((-120,-95),(120,-95)),2):
        home=editor.clone(point,f"forkliftHome{index}")
        place(home,home_x+dx,home_y+dy)
        space.appendChild(home)
        road=editor.clone(outbound,f"homePath{index}")
        road.setAttribute("TargetId",field(home,"Id"))
        place(road,home_x,home_y)
        set_points(road,route_curve([(0,0,0),(dx,dy,0)]))
        space.appendChild(road)
        homes.append(f"forkliftHome{index}")
    editor.block(blocks["forklift"],"forklift",975,480,
                 {"capacity":"3","homeNodes":"{ "+", ".join(homes)+" }"},package)
    editor.block(blocks["seizeForklift"],"seizeForklift",955,390,package=package)
    editor.block(blocks["conveyorExit"],"leaveBelt",1060,400,package=package)
    editor.block(blocks["toStorage"],"toWarehouse",1170,390,{
        "destinationNode":"((Carton) agent).isManuallyAdded ? manualWarehouse : " +
        "(((Carton) agent).isFragile ? fragileWarehouse : ordinaryWarehouse)"
    },package)
    editor.block(blocks["releaseForklift"],"releaseForklift",1295,390,package=package)
    editor.block(blocks["storing"],"storeBox",1420,390,package=package)
    place(editor.blocks["sink"],1770,400)
    set_param(editor.blocks["sink"],"onEnter",
              "if (agent.isManuallyAdded) manualDelivered++; else if (agent.isFragile) fragileDelivered++; else ordinaryDelivered++;")
    links = (("toConveyorEnd","seizeForklift",10,20),("seizeForklift","leaveBelt",20,10),
             ("leaveBelt","toWarehouse",10,20),("toWarehouse","releaseForklift",20,20),
             ("releaseForklift","storeBox",20,20),("storeBox","sink",20,10))
    for source,target,start,end in links:
        editor.connect(source,target,(40,start),(0,end))
    return ["3d/forklift.dae", "3d/sittingworker.dae"]


def extend_line(doc, model, main, network, component="blue_sleeve", layout="extended_offset"):
    editor = LineEditor(doc,model,main)
    existing_belts=by_name(child(network,"Presentation"),"Conveyor")
    existing_blocks=by_name(child(main,"EmbeddedObjects"),"EmbeddedObject")
    loading=[];shipping=[]
    if "partFeeder" not in existing_belts or not {"partSource","partTravel","fitPart"}.issubset(existing_blocks):
        enter,enter_model,enter_main=tutorial("ConveyorEnter")
        loading=build_loading(editor,network,enter_model,enter_main)
    else:
        _normalize_feeder(editor,network,main)
    existing_networks=by_name(child(main,"Presentation/Level/Presentation"),"Network")
    if "warehouseNetwork" not in existing_networks:
        exit_,exit_model,exit_main=tutorial("ConveyorExit")
        shipping=build_shipping(editor,network,exit_model,exit_main)

    view = by_name(child(main,"Areas"),"Area")["viewLogic"]
    place(view,-520,-25)
    put(view,"Width","2760" if layout=="extended_offset" else "2520")
    put(view,"Height","655")
    camera = main.getElementsByTagName("Camera3D")[0]
    place(camera,810,755)
    put(camera,"Z","1810")
    put(camera,"RotationX","72")
    put(camera,"RotationZ","-90")
    for window in main.getElementsByTagName("Control"):
        if window.getAttribute("Type") == "Window3D":
            put(window,"FarClippingDistance","4000")

    resources = child(model,"ModelResources")
    paths = []
    known = {field(r,"Path") for r in children(resources,"Resource")}
    tutorials=[]
    if loading: tutorials.append((enter,enter_model,loading))
    if shipping: tutorials.append((exit_,exit_model,shipping))
    for tutorial_path,tutorial_model,files in tutorials:
        for name in sorted(set(files)):
            if name in known:
                continue
            resource = next(r for r in children(child(tutorial_model,"ModelResources"),"Resource")
                            if field(r,"Path")==name)
            resources.appendChild(editor.clone(resource))
            paths.append(tutorial_path.parent / name)
            known.add(name)
    return paths


def _normalize_feeder(editor,network,main):
    """Keep an already staged 5.2 model aligned after geometry fixes."""
    belts=by_name(child(network,"Presentation"),"Conveyor")
    inlet=belts.get("loadingBelt",belts.get("conveyor"))
    part=belts.get("partFeeder")
    blocks=by_name(child(main,"EmbeddedObjects"),"EmbeddedObject")
    if inlet is None or part is None or "partSource" not in blocks:
        return
    join_x=round(float(field(inlet,"X"))+82)
    join_y=round(float(field(inlet,"Y")))
    start_y=join_y-180
    end_y=join_y+25
    place(part,join_x,start_y)
    set_points(part,route_curve([(0,0,0),(0,end_y-start_y,0)]))
    positions=by_name(child(part,"Presentation"),"PositionOnConveyor")
    for name,y in (("partStart",start_y),("partJoin",end_y)):
        if name in positions:
            place(positions[name],join_x,y)
    set_param(blocks["partSource"],"locationX",str(join_x))
    set_param(blocks["partSource"],"locationY",str(start_y))


def distinguish_cartons(doc, model, main):
    """Apply stable category cues on every generation, including staged models."""
    carton = by_name(child(model,"ActiveObjectClasses"),"ActiveObjectClass")["Carton"]
    shapes = child(carton,"Presentation/Level/Presentation")
    editor = LineEditor(doc,model,main)
    for node in list(children(shapes)):
        if field(node,"Name").startswith("categoryMark"):
            shapes.removeChild(node)
    base = by_name(shapes,"Rectangle")["carton2D"]
    put(base,"VisibleCode","!isComponent && !isManuallyAdded")
    manual = editor.clone(base,"categoryMarkManualBody")
    put(manual,"VisibleCode","!isComponent && isManuallyAdded")
    put(manual,"FillColor",str(argb("#2457CC")))
    shapes.appendChild(manual)
    for figure in children(shapes,"Figure3D"):
        if field(figure,"Name") in {"box_1_open1","box_1_closed1"}:
            for mapping in figure.getElementsByTagName("ColorMapping"):
                if field(mapping,"Name")=="MA_material_27":
                    put(mapping,"Color",str(argb("#2457CC")))
    # Color categories are integral to the mesh, so no 3D badge can float.
    put(base,"VisibleCode","!isComponent && !isManuallyAdded && !isFragile")
    put(manual,"VisibleCode","!isComponent && isManuallyAdded && !isFragile")
    fragile_body=editor.clone(base,"categoryMarkFragileBody")
    put(fragile_body,"FillColor",str(argb("#F28A3C")))
    put(fragile_body,"VisibleCode","!isComponent && isFragile")
    shapes.appendChild(fragile_body)
    for figure in list(children(shapes,"Figure3D")):
        if field(figure,"Name") not in {"box_1_open","box_1_closed","box_1_open1","box_1_closed1"}:
            continue
        original=field(figure,"VisibleCode").split(" && !isFragile")[0]
        put(figure,"VisibleCode",original+" && !isFragile && !isComponent")
        duplicate=editor.clone(figure,"categoryMarkFragile"+field(figure,"Name"))
        put(duplicate,"VisibleCode",original+" && isFragile && !isComponent")
        for mapping in duplicate.getElementsByTagName("ColorMapping"):
            if field(mapping,"Name")=="MA_material_27":
                put(mapping,"Color",str(argb("#F28A3C")))
            elif field(mapping,"Name")=="MA_material_28":
                put(mapping,"Color",str(argb("#FFFFFF")))
        shapes.appendChild(duplicate)
    # Flat vector icons are restricted to 2D.
    # Four orange sides mark fragile boxes; a white P marks manual assembly.
    def stroke(name,x,y,w,h,color,condition):
        node=editor.clone(base,"categoryMark"+name)
        place(node,x,y)
        for key,value in {"Width":str(w),"Height":str(h),"Z":"44",
                          "ZHeight":"1","DrawMode":"SHAPE_DRAW_2D3D",
                          "FillColor":str(argb(color)),"VisibleCode":condition}.items():
            put(node,key,value)
        put(node,"DrawMode","SHAPE_DRAW_2D")
        shapes.appendChild(node)
    fragile="!isComponent && isFragile"
    for name,x,y,w,h in [("Top",-21,-21,42,5),("Bottom",-21,16,42,5),
                         ("Left",-21,-16,5,32),("Right",16,-16,5,32)]:
        stroke(name,x,y,w,h,"#FF6500",fragile)
    # Glass silhouette, kept independent of isSealed.
    for name,x,y,w,h in [("GlassRim",-8,-12,16,4),("GlassBowl",-6,-8,12,9),
                         ("GlassStem",-2,1,4,8),("GlassFoot",-7,9,14,4)]:
        stroke(name,x,y,w,h,"#202536",fragile)
    manual="!isComponent && isManuallyAdded"
    for name,x,y,w,h in [("PStem",-15,-12,4,25),("PTop",-11,-12,11,4),
                         ("PRight",-3,-8,4,7),("PMid",-11,-1,11,4)]:
        stroke(name,x,y,w,h,"#FFFFFF",manual)


def restore_tabbed_views(doc, model, main):
    """Preserve the reference's tab navigation; separate the enlarged 2D area."""
    areas=by_name(child(main,"Areas"),"Area")
    logic,view3d=areas["viewLogic"],areas["view3D"]
    place(view3d,5000,0)
    for window in main.getElementsByTagName("Control"):
        if window.getAttribute("Type")=="Window3D":
            place(window,5000,50)
            put(window,"FollowCamera","true")
            put(window,"MakeDefaultViewArea","false")
            put(window,"Width","1000");put(window,"Height","550")
    # Reserve a header band in model coordinates at the overview zoom.
    put(logic,"Y","-220")
    put(logic,"Height","1100")
    networks=by_name(child(main,"Presentation/Level/Presentation"),"Network")
    if "warehouseNetwork" not in networks:
        place(logic,-520,-220)
        put(logic,"Width","1800")
        camera=next(iter(main.getElementsByTagName("Camera3D")))
        for key,value in {"X":"500","Y":"700","Z":"1500","RotationX":"72","RotationZ":"-90"}.items():
            put(camera,key,value)
    width=float(field(logic,"Width"))
    # Match the frame aspect ratio: navigateTo then has no centering band
    # above the header. Lock model-level dragging; 3D navigation stays local.
    put(logic,"Height",str(round(width*0.6)))
    fn=by_name(child(main,"Functions"),"Function")["navigate"]
    put(fn,"Body", "selectedViewArea = viewArea;\n"
        + "viewArea.navigateTo();\n"
        + "getPresentation().setZoom(viewArea == viewLogic ? 1000.0 / viewLogic.getWidth() : 1.0);\n"
        + "getPresentation().setCenter(viewArea.getX() + viewArea.getWidth()/2, viewArea.getY() + viewArea.getHeight()/2);\n"
        + "getPresentation().setZoomAndPanningEnabled(false);\n"
        + "panelGroup.setPos(viewArea.getX() + 500, viewArea.getY() + 20);")
    for n in children(child(main,"Variables"))+children(child(main,"Functions")):
        put(n,"PresentationFlag","false")
    put(child(model,"Experiments/SimulationExperiment/PresentationProperties"),"EnableZoomAndPanning","false")
    put(main,"StartupCode","navigate(viewLogic);")

    # Keep the original previews outside Carton, including forklift drivers.
    for agent in children(child(model,"ActiveObjectClasses"),"ActiveObjectClass"):
        if field(agent,"Name")!="Carton":
            for figure in agent.getElementsByTagName("Figure3D"):
                put(figure,"DrawMode","SHAPE_DRAW_2D3D")
    carton=by_name(child(model,"ActiveObjectClasses"),"ActiveObjectClass")["Carton"]
    shapes=child(carton,"Presentation/Level/Presentation")
    for shape in children(shapes):
        if field(shape,"Name")=="blueSleeve":
            put(shape,"ZCode","isComponent ? 0 : 8")
        if field(shape,"Name")=="blueSleeve2D":
            shapes.appendChild(shape)
    # Logical source stays with its flowchart, not on the physical feeder.
    blocks=by_name(child(main,"EmbeddedObjects"),"EmbeddedObject")
    if "partSource" in blocks and "partTravel" in blocks:
        place(blocks["partSource"],-455,580)
        editor=LineEditor(doc,model,main)
        editor.unlink("partSource","partTravel")
        editor.connect("partSource","partTravel",(30,10),(0,10))
    for text in main.getElementsByTagName("Text"):
        if field(text,"Name") in {"ordinaryWarehouseLabel","fragileWarehouseLabel","manualWarehouseLabel"}:
            put(text,"Y",str(float(field(text,"Y"))-40))
            # Do not accumulate the offset when reusing an already patched model.
            put(text,"Name",field(text,"Name")+"Adjusted")
