"""Real pallet inventory and an explicit manual loading lane for LR5."""
from pathlib import Path

from bridge.anylogic import put
from models import anchors, child, children, field, load, route_curve, set_points
from conveyor import LineEditor, by_name, place, set_param


def _layout(editor):
    for name,x,y in [("source",-650,400),("fitPallet",-530,400),
                     ("fitSheet",-390,400),("loadingGate",-260,400),
                     ("loadingTravel",-130,400),("fitPart",20,400),
                     ("stockPallets",-650,480),("palletStockBuffer",-560,480),
                     ("sheetSource",-650,560),("partSource",-650,640),
                     ("partTravel",-240,640)]:
        place(editor.blocks[name],x,y)
    for source,target,start,end,bends,port in [
        ("source","fitPallet",(30,10),(10,10),(),"in1"),
        ("fitPallet","fitSheet",(30,10),(10,10),(),"in1"),
        ("stockPallets","palletStockBuffer",(30,10),(0,10),(),"in"),
        ("palletStockBuffer","fitPallet",(30,10),(0,30),((-530,490),),"in2"),
        ("sheetSource","fitSheet",(30,10),(0,30),((-390,570),),"in2"),
        ("fitSheet","loadingGate",(30,10),(0,10),(),"in"),
        ("loadingGate","loadingTravel",(20,10),(0,10),(),"in"),
        ("loadingTravel","fitPart",(40,10),(10,10),(),"in1"),
        ("partSource","partTravel",(30,10),(0,10),(),"in"),
        ("partTravel","fitPart",(40,10),(0,30),((20,650),),"in2"),
        ("fitPart","fromConveyorStart",(30,10),(0,10),(),"in")]:
        editor.unlink(source,target)
        editor.connect(source,target,start,end,bends,port)


def ensure_supply(doc, model, main):
    editor = LineEditor(doc, model, main)
    if "stockPallets" in editor.blocks:
        _layout(editor)
        return
    import anylab
    tutorial = Path(anylab.examples("ConveyorEnter")[0])
    _, example = load(tutorial)
    example_main = by_name(child(example, "ActiveObjectClasses"), "ActiveObjectClass")["Main"]
    queue = by_name(child(example_main, "EmbeddedObjects"), "EmbeddedObject")["palletBuffer1"]
    queue = editor.clone(queue, "palletStockBuffer", field(example, "JavaPackageName"))
    for code in queue.getElementsByTagName("Code"):
        if code.firstChild:
            code.firstChild.data = code.firstChild.data.replace("Pallet", "Carton")
    place(queue, -570, 520)
    editor.embedded.appendChild(queue)
    editor.blocks["palletStockBuffer"] = queue
    for key, value in {"capacity":"6", "maximumCapacity":"false", "entityLocation":"palletStaging"}.items():
        set_param(queue, key, value)
    stock = editor.block(editor.blocks["sheetSource"], "stockPallets", -680, 520,
                         {"onBeforeArrival":"", "onAtExit":"", "onExit":""})
    combine = editor.block(editor.blocks["fitSheet"], "fitPallet", -460, 400,
                           {"onExit":"palletsTaken++; stockPallets.inject(1);"})
    editor.unlink("source", "fitSheet")
    editor.connect("source", "fitPallet", (10,0), (-10,0), target_port="in1")
    editor.connect("fitPallet", "fitSheet", (10,0), (-10,0), target_port="in1")
    editor.connect("stockPallets", "palletStockBuffer", (10,0), (-10,0))
    editor.connect("palletStockBuffer", "fitPallet", (10,0), (0,10),
                   bends=((-490,520),(-490,440),(-460,440)), target_port="in2")

    _, reference = load(Path(__file__).parent/"templates/models/5.2/1/ConveyorLine.alp")
    reference_main = by_name(child(reference,"ActiveObjectClasses"),"ActiveObjectClass")["Main"]
    prototype = next(n for n in reference_main.getElementsByTagName("RectangleNode")
                     if field(n,"Name")=="ordinaryWarehouse")
    node = editor.clone(prototype,"palletStaging",field(reference,"JavaPackageName"))
    network = next(iter(main.getElementsByTagName("ConveyorNetwork")))
    belts = by_name(child(network,"Presentation"),"Conveyor")
    inlet = belts.get("loadingBelt",belts["conveyor"])
    x, y = float(field(inlet,"X"))-260, float(field(inlet,"Y"))-60
    for key,value in {"X":x,"Y":y,"Z":0,"Width":220,"Height":120}.items():put(node,key,str(value))
    for end in children(node,"PathEnd"):node.removeChild(end)
    for container in children(node,"PathEnds"):
        node.removeChild(container)
    # Attractor coordinates are absolute in the model, as in the supplied ALP.
    for i,attractor in enumerate(node.getElementsByTagName("Attractor")):
        put(attractor,"Name","stockPlace"+str(i))
        place(attractor,x+35+(i%3)*70,y+30+(i//3)*60)
        put(attractor,"Z","0")
    presentation = child(main,"Presentation/Level/Presentation")
    presentation.appendChild(node)
    editor.caption("stockLabel","Запас поддонов: 6\nПополнение после выдачи",int(x),int(y-25))

    # Hand-assembled cartons start at their own workstation and travel on a
    # short real conveyor ending before the main belt; the operator loads it
    # through fromPosition only when the main conveyor accepts the carton.
    lane = editor.clone(belts["partFeeder"],"manualFeeder")
    for name in ("SourceId","TargetId"):
        if lane.hasAttribute(name):lane.removeAttribute(name)
    lane_presentation = child(lane,"Presentation")
    for n in list(children(lane_presentation)):
        lane_presentation.removeChild(n)
    primary = belts["conveyor"]
    join = next(n for n in primary.getElementsByTagName("PositionOnConveyor")
                if field(n,"Name")=="placingPoint")
    join_x = float(field(primary,"X"))+float(field(join,"Offset"))-100/6
    join_y = float(field(primary,"Y"))
    place(lane,join_x,join_y-70)
    set_points(lane,route_curve([(0,0,0),(0,50,0)]))
    lane.replaceChild(child(primary,"Width").cloneNode(True),child(lane,"Width"))
    end_proto = next(n for n in belts["partFeeder"].getElementsByTagName("PositionOnConveyor")
                     if field(n,"Name")=="partJoin")
    end = editor.clone(end_proto,"manualJoin")
    put(end,"Offset",str(20+100/6))
    place(end,join_x+20,join_y)
    lane_presentation.appendChild(end)
    child(network,"Presentation").appendChild(lane)
    travel = editor.block(editor.blocks["partTravel"],"manualTravel",200,535,
                          {"sourceType":"self.SOURCE_CONVEYOR_OFFSET",
                           "sourceConveyor":"manualFeeder","sourceOffsetFromBeginning":"true",
                           "sourceOffset":"0","targetPositionOnConveyor":"manualJoin",
                           "targetConveyor":"manualFeeder","removeFromConveyor":"true",
                           "onExit":"manualFed++;"})
    editor.unlink("source1","fromPosition")
    editor.connect("source1","manualTravel",(10,0),(-10,0),bends=((180,470),(180,535)))
    editor.connect("manualTravel","fromPosition",(10,0),(-10,0),bends=((245,535),(245,470)))
    static_box = next((n for n in main.getElementsByTagName("Figure3D")
                       if field(n,"Name")=="box_1_open"),None)
    if static_box is not None:put(static_box,"VisibleCode","false")
    editor.caption("manualFeedLabel","Ручная сборка → подача синей коробки",110,120)
    variables = by_name(child(main,"Variables"),"Variable")
    for name in ("palletsTaken","manualFed"):
        editor.variable(main,variables["assembled"],name,"0",1320,"int")
    startup = field(main,"StartupCode")
    put(main,"StartupCode",startup+"\nstockPallets.inject(6);\n")
    _layout(editor)
