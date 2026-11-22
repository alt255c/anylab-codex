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
    inlet = by_name(belt_shapes,"Conveyor")["loadingBelt"]
    part = editor.clone(inlet,"partFeeder")
    part.removeAttribute("TargetId")
    join_x = float(field(inlet,"X"))+82
    join_y = float(field(inlet,"Y"))
    place(part,join_x,join_y-155)
    set_points(part,route_curve([(0,0,0),(0,117,0)]))
    belt_shapes.appendChild(part)
    editor.caption("loadingText","Подача детали ↓",int(join_x)-72,int(join_y)-176)

    package = field(enter_model,"JavaPackageName")
    blocks = by_name(child(enter_main,"EmbeddedObjects"),"EmbeddedObject")
    source, manual, convey = (editor.blocks[k] for k in ("source","source1","fromConveyorStart"))
    place(source,-455,400)
    editor.block(manual,"sheetSource",-455,520,{"onAtExit":"agent.isComponent = true;"})
    editor.block(manual,"partSource",-455,580,{"onAtExit":"agent.isComponent = true;"})
    # Inject exactly one part and one sheet for each pallet.
    set_param(source,"onAtExit","sheetSource.inject(1); partSource.inject(1);")
    set_param(source,"locationX",str(float(field(inlet,"X"))))
    set_param(source,"locationY",str(join_y))
    travel = editor.block(convey,"partTravel",-270,580,{
        "sourceConveyor":"partFeeder","targetConveyor":"partFeeder",
    })
    parameters = by_name(child(travel,"Parameters"),"Parameter")
    for setting in ("targetType","targetPositionOnConveyor"):
        parameters[setting].removeChild(child(parameters[setting],"Value"))
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
        dest.appendChild(duplicate)
        assets.extend(n.firstChild.data for n in duplicate.getElementsByTagName("ClassName")
                      if n.firstChild and n.firstChild.data.startswith("3d/"))
    return assets


def build_shipping(editor, network, exit_model, exit_main):
    package = field(exit_model,"JavaPackageName")
    blocks = by_name(child(exit_main,"EmbeddedObjects"),"EmbeddedObject")
    forklift = by_name(child(exit_model,"ActiveObjectClasses"), "ActiveObjectClass")["Forklift"]
    child(editor.model,"ActiveObjectClasses").appendChild(editor.clone(forklift,imported_package=package))

    belt = by_name(child(network,"Presentation"),"Conveyor")["unloadingBelt"]
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
    put(store,"Width","100")
    put(store,"Height","72")
    for name, delta, label in (("fragileWarehouse",-95,"Хрупкие"),("manualWarehouse",95,"Ручная сборка")):
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
    editor.block(blocks["forklift"],"forklift",975,480,{"capacity":"3"},package)
    editor.block(blocks["seizeForklift"],"seizeForklift",955,390,package=package)
    editor.block(blocks["conveyorExit"],"leaveBelt",1060,400,package=package)
    editor.block(blocks["toStorage"],"toWarehouse",1170,390,{
        "destinationNode":"((Carton) agent).isManuallyAdded ? manualWarehouse : " +
        "(((Carton) agent).isFragile ? fragileWarehouse : ordinaryWarehouse)"
    },package)
    editor.block(blocks["releaseForklift"],"releaseForklift",1295,390,package=package)
    editor.block(blocks["storing"],"storeBox",1420,390,package=package)
    place(editor.blocks["sink"],1540,400)
    set_param(editor.blocks["sink"],"onEnter",
              "if (agent.isManuallyAdded) manualDelivered++; else if (agent.isFragile) fragileDelivered++; else ordinaryDelivered++;")
    links = (("toConveyorEnd","seizeForklift",10,20),("seizeForklift","leaveBelt",20,10),
             ("leaveBelt","toWarehouse",10,20),("toWarehouse","releaseForklift",20,20),
             ("releaseForklift","storeBox",20,20),("storeBox","sink",20,10))
    for source,target,start,end in links:
        editor.connect(source,target,(40,start),(0,end))
    return ["3d/forklift.dae", "3d/sittingworker.dae"]


def extend_line(doc, model, main, network):
    editor = LineEditor(doc,model,main)
    enter, enter_model, enter_main = tutorial("ConveyorEnter")
    exit_, exit_model, exit_main = tutorial("ConveyorExit")
    loading = build_loading(editor,network,enter_model,enter_main)
    shipping = build_shipping(editor,network,exit_model,exit_main)

    view = by_name(child(main,"Areas"),"Area")["viewLogic"]
    place(view,-520,-25)
    put(view,"Width","2530")
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
    for tutorial_path,tutorial_model,files in ((enter,enter_model,loading),(exit_,exit_model,shipping)):
        for name in sorted(set(files)):
            if name in known:
                continue
            resource = next(r for r in children(child(tutorial_model,"ModelResources"),"Resource")
                            if field(r,"Path")==name)
            resources.appendChild(editor.clone(resource))
            paths.append(tutorial_path.parent / name)
            known.add(name)
    return paths
