"""Explicit cargo roles and native 2D/3D geometry for the LR5 assembly line.

Roles distinguish a pallet, loose part, sheet and assembled carton before any
presentation is sent. Native shapes have independent per-agent state; a cached
COLLADA material cannot recolor another category or retain an open carton.
"""
from pathlib import Path

from bridge.anylogic import put
from models import child, children, field, load
from conveyor import LineEditor, by_name, set_param, argb


def apply_cargo(doc, model, main, body="#19B6B0", accent="#F28A3C", component="#2867D1"):
    existing=by_name(child(model,'ActiveObjectClasses'),'ActiveObjectClass').get('Carton')
    if existing is not None and 'cargoRole' in by_name(child(existing,'Variables'),'Variable'):
        from lr5_revision import revise
        revise(doc,model,main,any(field(n,'Name')=='warehouseNetwork' for n in main.getElementsByTagName('Network')))
        validate_cargo(main)
        return {'geometry':'native_static_category_colors','preserved':True}
    from supply import ensure_supply
    ensure_supply(doc,model,main)
    editor=LineEditor(doc,model,main)
    carton=by_name(child(model,"ActiveObjectClasses"),"ActiveObjectClass")["Carton"]
    variables=by_name(child(carton,"Variables"),"Variable")
    for name,kind,value in (("cargoRole","int","0"),("cargoReady","boolean","false")):
        if name not in variables:editor.variable(carton,variables["isSealed"],name,value,400,kind)
    for variable in children(child(carton,"Variables"),"Variable"):
        put(variable,"PresentationFlag","false")
    # The Source callback runs after agent initialization and before handover.
    initialize={
        "source":"cargoRole=0; isComponent=false; isManuallyAdded=false; isSealed=false; hasPalletSheet=false; hasAssemblyPart=false;",
        "partSource":"cargoRole=1; isComponent=true; isFragile=false; isManuallyAdded=false; isSealed=false;",
        "sheetSource":"cargoRole=2; isComponent=false; isFragile=false; isManuallyAdded=false; isSealed=false;",
        "source1":"cargoRole=3; isComponent=false; isFragile=false; isManuallyAdded=true; isSealed=false; hasPalletSheet=false; hasAssemblyPart=true;",
        "stockPallets":"cargoRole=4; isComponent=false; isFragile=false; isManuallyAdded=false; isSealed=false; hasPalletSheet=false; hasAssemblyPart=false;"}
    for name,code in initialize.items():
        actions=" ".join("agent."+statement.strip()+";" for statement in code.split(";") if statement.strip())
        # Main and manual cartons become visible only once they physically
        # enter their belt. A queued Source/Combine must not paint a second
        # carton over an item already travelling through the loading point.
        ready="false" if name in {"source","source1"} else "true"
        set_param(editor.blocks[name],"onAtExit",actions+" agent.cargoReady="+ready+";")
    network=next(iter(main.getElementsByTagName("ConveyorNetwork")))
    belts=by_name(child(network,"Presentation"),"Conveyor")
    inlet=belts.get("loadingBelt",belts["conveyor"])
    for name,belt in (("source",inlet),("partSource",belts["partFeeder"]),("source1",belts["manualFeeder"])):
        b=editor.blocks[name]
        old=field(by_name(child(b,"Parameters"),"Parameter")["onAtExit"],"Value/Code")
        set_param(b,"onAtExit",old+" agent.setXY("+field(belt,"X")+","+field(belt,"Y")+");")
    for belt in belts.values():
        set_param(child(belt,"EmbeddedObject"),"onLeadingEdgeEnter","agent.cargoReady=true; agent.refreshCargo();")
    manual=belts["manualFeeder"]
    from models import set_points,route_curve
    set_points(manual,route_curve([(0,0,0),(0,50,0)]))
    manual_join=next(p for p in manual.getElementsByTagName("PositionOnConveyor") if field(p,"Name")=="manualJoin")
    put(manual_join,"Offset",str(20+100/6))
    set_param(editor.blocks["manualTravel"],"onExit","manualFed++; agent.refreshCargo();")
    # Combine waits for both inputs before accepting a Source handover. Supplies
    # must exist on arrival; injecting them onAtExit would deadlock that handover.
    set_param(editor.blocks["source"],"onBeforeArrival","sheetSource.inject(1); partSource.inject(1);")
    set_param(editor.blocks["fitSheet"],"onExit","agent.hasPalletSheet=true;")
    set_param(editor.blocks["fitPart"],"onExit","agent.hasAssemblyPart=true; agent.cargoRole=3; assembled++; loadingGate.unblock();")
    set_param(editor.blocks["loadingTravel"],"removeFromConveyor","false")
    set_param(editor.blocks["fromConveyorStart"],"sourceType","self.SOURCE_CURRENT_POSITION")
    set_param(editor.blocks["fromConveyorStart"],"onExit","")
    # Set physical footprints to match their visible geometry (scale 33.33 px/m).
    for name,length,width in (("source",1.2,.96),("source1",1.0,.90),("partSource",.30,.30),("sheetSource",.96,.90),("stockPallets",1.2,.96)):
        b=editor.blocks[name]
        set_param(b,"changeDimensions","true")
        for key,value in (("length",length),("width",width),("height",.6)):
            set_param(b,key,str(value))
            v=child(by_name(child(b,"Parameters"),"Parameter")[key],"Value")
            v.setAttribute("Class","CodeUnitValue")
            unit=child(v,"Unit")
            if unit is None:unit=v.appendChild(doc.createElement("Unit"))
            unit.setAttribute("Class","LengthUnits");put(v,"Unit","METER")
    # Target offsets refer to leading edge. Place centers at the intersection.
    for name,offset in (("assemblyJoin",102.0),("partJoin",185.0)):
        position=next(p for p in main.getElementsByTagName("PositionOnConveyor") if field(p,"Name")==name)
        put(position,"Offset",str(offset))
    # Packaging invariants are checked at the physical exit and delivery.
    variables=by_name(child(main,"Variables"),"Variable")
    for name in ("packedOrdinary","packedFragile","packedManual","unsealedOutput","invalidOutput"):
        if name not in variables:editor.variable(main,variables["assembled"],name,"0",1300,"int")
    for station in main.getElementsByTagName("ConveyorSimpleStation"):
        block=child(station,"EmbeddedObject")
        set_param(block,"onProcessFinished","agent.isSealed=true; if(agent.isManuallyAdded) packedManual++; else if(agent.isFragile) packedFragile++; else packedOrdinary++;")
    set_param(editor.blocks["toConveyorEnd"],"onExit","if(!agent.isSealed) unsealedOutput++; if(agent.cargoRole!=3 || !agent.hasAssemblyPart) invalidOutput++;")
    for variable in children(child(main,"Variables"),"Variable"):put(variable,"PresentationFlag","false")

    shapes=child(carton,"Presentation/Level/Presentation")
    rect=next(n for n in children(shapes,"Rectangle"))
    _,oval_model=load(Path(__file__).parent/"templates/models/1.3/1/Model.alp")
    oval=oval_model.getElementsByTagName("Oval")[0]
    for node in list(children(shapes)):shapes.removeChild(node)
    ready="cargoReady"
    pallet=ready+" && !isManuallyAdded && (cargoRole==0 || cargoRole==3 || cargoRole==4)"
    box=ready+" && (cargoRole==0 || cargoRole==3)"
    loose=ready+" && cargoRole==1"
    def shape(proto,name,x,y,w,h,z,depth,color,visible,mode="SHAPE_DRAW_2D3D"):
        n=editor.clone(proto,name)
        for key in ("OnClickCode","FillColorCode","LineColorCode","VisibleCode","ZCode","XCode","YCode","WidthCode","HeightCode","ZHeightCode"):
            for old in children(n,key):n.removeChild(old)
        for key,val in {"X":x,"Y":y,"Z":z,"ZHeight":depth,"LineWidth":0,"LineColor":argb(color),"FillColor":argb(color),"DrawMode":mode,"VisibleCode":visible,"ShowLabel":"false"}.items():put(n,key,str(val))
        if n.tagName=="Oval":put(n,"RadiusX",str(w));put(n,"RadiusY",str(h))
        else:put(n,"Width",str(w));put(n,"Height",str(h))
        shapes.appendChild(n);return n
    for i,y in enumerate((-18,-5,8)):shape(rect,"palletSlat"+str(i),-19,y,38,10,0,3,"#AB865D",pallet)
    shape(rect,"palletRail1",-16,-19,6,38,3,2,"#8C6946",pallet,"SHAPE_DRAW_3D")
    shape(rect,"palletRail2",10,-19,6,38,3,2,"#8C6946",pallet,"SHAPE_DRAW_3D")
    shape(rect,"sheet",-16,-16,32,32,5,1,"#FFF1CF",ready+" && ((cargoRole==0 && hasPalletSheet) || (cargoRole==3 && !isManuallyAdded))")
    # Static per-category fill AND edge colors avoid stale/default turquoise
    # faces in 3D. Visibility chooses one category, never recolors a mesh.
    fragile_color="#9B4A8C" if body.upper()=="#E88448" else "#F28A3C"
    categories=[("",body,"!isFragile && !isManuallyAdded"),
                ("fragile_",fragile_color,"isFragile"),
                ("manual_","#2457CC","isManuallyAdded && !isFragile")]
    for prefix,color,condition in categories:
        category=box+" && ("+condition+")"
        base=-6 if prefix=="manual_" else 0
        for name,x,y,w,h,z,dep in (("floor",-15,-15,30,30,6,1),("front",-15,-15,30,2,7,17),("back",-15,13,30,2,7,17),("left",-15,-13,2,26,7,17),("right",13,-13,2,26,7,17)):
            shape(rect,prefix+"box"+name,x,y,w,h,z+base,dep,color,category,"SHAPE_DRAW_3D")
        for name,x,y,w,h in (("front",-15,-24,30,9),("back",-15,15,30,9),("left",-24,-13,9,26),("right",15,-13,9,26)):
            shape(rect,prefix+"flap"+name,x,y,w,h,24+base,1,color,category+" && !isSealed","SHAPE_DRAW_3D")
        shape(rect,prefix+"closedLid",-15,-15,30,30,24+base,1,color,category+" && isSealed","SHAPE_DRAW_3D")
        shape(rect,prefix+"carton2D",-15,-15,30,30,26,0,color,category,"SHAPE_DRAW_2D")
    tape=shape(rect,"tape3D",-3,-15,6,30,25,0.3,accent,box+" && isSealed","SHAPE_DRAW_3D")
    put(tape,"ZCode","isManuallyAdded ? 19 : 25")
    # A real cylinder and recessed bore are native objects, not a cached mesh.
    part_visible=loose+" || ("+box+" && hasAssemblyPart && !isSealed)"
    component3=shape(oval,"component3D",0,0,5,5,0,8,component,part_visible,"SHAPE_DRAW_3D")
    put(component3,"ZCode","cargoRole==1 ? 0 : (isManuallyAdded ? 2 : 8)")
    hole=shape(oval,"bore3D",0,0,2.6,2.6,8.1,.1,"#102B4B",part_visible,"SHAPE_DRAW_3D")
    put(hole,"ZCode","cargoRole==1 ? 8.1 : (isManuallyAdded ? 10.1 : 16.1)")
    # 2D is drawn explicitly, with an open cavity and a closed taped lid.
    shape(rect,"openInterior2D",-11,-11,22,22,27,0,"#FFF1CF",box+" && !isSealed","SHAPE_DRAW_2D")
    shape(rect,"tape2D",-3,-15,6,30,27,0,accent,box+" && isSealed","SHAPE_DRAW_2D")
    shape(oval,"component2D",0,0,5,5,28,0,component,part_visible,"SHAPE_DRAW_2D")
    shape(oval,"bore2D",0,0,2.5,2.5,29,0,"#102B4B",part_visible,"SHAPE_DRAW_2D")
    for name,x,y,w,h in (("glassRim",-6,-9,12,3),("glassBowl",-5,-6,10,7),("glassStem",-1,1,2,6),("glassFoot",-5,7,10,2)):
        shape(rect,name,x,y,w,h,30,0,"#292A30",box+" && isFragile","SHAPE_DRAW_2D")
    for name,x,y,w,h in (("manualStem",-10,-8,3,17),("manualTop",-7,-8,9,3),("manualRight",0,-5,3,5),("manualMid",-7,0,9,3)):
        shape(rect,name,x,y,w,h,31,0,"#FFFFFF",box+" && isManuallyAdded","SHAPE_DRAW_2D")
    # Push state changes to the animation immediately. A packed carton can be
    # outside the current 3D view when its station callback runs; deferring the
    # refresh until a later render may otherwise retain the old open surfaces.
    functions=child(carton,"Functions")
    if functions is None:functions=carton.appendChild(doc.createElement("Functions"))
    refresh=by_name(functions,"Function").get("refreshCargo")
    if refresh is None:
        refresh=editor.clone(by_name(child(main,"Functions"),"Function")["navigate"],"refreshCargo")
        for parameter in children(refresh,"Parameter"):refresh.removeChild(parameter)
        functions.appendChild(refresh)
    put(refresh,"PublicFlag","true");put(refresh,"PresentationFlag","false")
    code=[]
    for node in children(shapes):
        code.append(field(node,"Name")+".setVisible("+field(node,"VisibleCode")+");")
        code.append(field(node,"Name")+".updateDynamicProperties();")
    put(refresh,"Body","\n".join(code))
    put(carton,"StartupCode","refreshCargo();")
    for block,event in [(name,"onAtExit") for name in initialize]+[("fitSheet","onExit"),("fitPart","onExit")]:
        b=editor.blocks[block];old=field(by_name(child(b,"Parameters"),"Parameter")[event],"Value/Code")
        set_param(b,event,old+" agent.refreshCargo();")
    for station in main.getElementsByTagName("ConveyorSimpleStation"):
        b=child(station,"EmbeddedObject");old=field(by_name(child(b,"Parameters"),"Parameter")["onProcessFinished"],"Value/Code")
        set_param(b,"onProcessFinished",old+" agent.refreshCargo();")
    functions_main=child(main,"Functions")
    anchor=by_name(functions_main,"Function").get("anchorTabs")
    if anchor is None:
        anchor=editor.clone(by_name(functions_main,"Function")["navigate"],"anchorTabs")
        for parameter in children(anchor,"Parameter"):anchor.removeChild(parameter)
        functions_main.appendChild(anchor)
    put(anchor,"PresentationFlag","false")
    put(anchor,"Body","""com.anylogic.engine.presentation.INavigationPoint view = getPresentation().getCurrentNavigationPoint();
if(getPresentation().isZoomAndPanningEnabled() && view != null && view.getPresentable() == this && view.getWidth() > 0) {
    // AnyLogic 8.9 navigation snapshots pad the actual viewport by 50% on each side.
    double width = view.getWidth()/2.0;
    double top = view.getY()+view.getHeight()/4.0;
    double scale = width/1000.0;
    panelGroup.setScale(scale);
    panelGroup.setPos(view.getX()+view.getWidth()/2.0, top+20*scale);
}""")
    # Re-evaluate anchoring on animation updates as well as model events, including pause.
    bar_width=by_name(functions_main,"Function").get("tabBarWidth")
    if bar_width is None:
        bar_width=editor.clone(anchor,"tabBarWidth");functions_main.appendChild(bar_width)
    put(bar_width,"ReturnModificator","RETURNS_VALUE");put(bar_width,"ReturnType","double")
    put(bar_width,"Body","anchorTabs(); return 1000;")
    panel=next(n for n in main.getElementsByTagName("Group") if field(n,"Name")=="panelGroup")
    panel.parentNode.appendChild(panel)
    bar=next(n for n in panel.getElementsByTagName("Rectangle") if field(n,"Name")=="rectangle")
    put(bar,"WidthCode","tabBarWidth()")
    logic=next(n for n in children(child(main,"Areas"),"Area") if field(n,"Name")=="viewLogic")
    for key,value in {"X":-700,"Y":-160,"Width":1333,"Height":800}.items():put(logic,key,str(value))
    view3d=next(n for n in children(child(main,"Areas"),"Area") if field(n,"Name")=="view3D")
    put(view3d,"X","5000")
    window=next(n for n in main.getElementsByTagName("Control") if field(n,"Name")=="window3d")
    put(window,"X","5000")
    nav=by_name(functions_main,"Function")["navigate"]
    put(nav,"Body","selectedViewArea = viewArea; viewArea.navigateTo(); anchorTabs();")
    startup=field(main,"StartupCode")
    if "AnyLabFixedTabs" not in startup:
        put(main,"StartupCode",startup+"""
class AnyLabFixedTabs extends com.anylogic.engine.DynamicEvent {
    AnyLabFixedTabs() { super(Main.this,.15); }
    @Override public void execute() { anchorTabs(); new AnyLabFixedTabs(); }
}
new AnyLabFixedTabs();
navigate(viewLogic);
""")
    # Sheets consumed by Combine stay invisible, including while queued.
    from lr5_revision import revise
    revise(doc,model,main,any(field(n,'Name')=='warehouseNetwork' for n in main.getElementsByTagName('Network')))
    return {"roles":["pallet_before_assembly","part","sheet","assembled_carton","stock_pallet"],"geometry":"native_static_category_colors", "parts_center_offset":185,"pallet_center_offset":102}


def validate_cargo(main):
    blocks=by_name(child(main,"EmbeddedObjects"),"EmbeddedObject")
    def code(block,key):return field(by_name(child(blocks[block],"Parameters"),"Parameter")[key],"Value/Code")
    if code("fromConveyorStart","sourceType")!="self.SOURCE_CURRENT_POSITION" or code("loadingTravel","removeFromConveyor")!="false":
        raise ValueError("Поддон должен непрерывно оставаться на основной ленте при сборке")
    if 'foldBox' in blocks:
        if code('fromConveyorStart','targetPositionOnConveyor')!='foldPoint' or code('fromConveyorStart','removeFromConveyor')!='false':
            raise ValueError('Заготовка должна останавливаться у работника на ленте')
        if 'agent.boxFormed=true;' not in code('foldBox','onExit') or 'boxFormed=true' in code('fitPart','onExit'):
            raise ValueError('Коробка формируется после задержки у работника, а не в месте подачи детали')
        if 'conveyorEnter' in blocks and (code('conveyorEnter','conveyor')!='loadingBelt' or code('liftUp','entityLocation')!='palletLiftPath'):
            raise ValueError('Поддон должен поступать на входную ленту через ConveyorEnter')
    for name,role in (("source",0),("partSource",1),("sheetSource",2),("source1",3),("stockPallets",4)):
        if name not in blocks and name in {"sheetSource","stockPallets"}:continue
        if f"agent.cargoRole={role};" not in code(name,"onAtExit"):
            raise ValueError("Неверная роль источника "+name)
    positions={field(p,"Name"):p for p in main.getElementsByTagName("PositionOnConveyor")}
    for name,offset in (("partStart",0),("partJoin",185),("assemblyJoin",102)):
        if abs(float(field(positions[name],"Offset"))-offset)>1e-6:raise ValueError("Неверная точка центрирования "+name)
    if "inject" not in code("source","onBeforeArrival"):raise ValueError("Комплектующие должны поступать до приёма поддона Combine")
    if code("manualTravel","sourceConveyor")!="manualFeeder" or code("manualTravel","targetPositionOnConveyor")!="manualJoin":
        raise ValueError("Ручная коробка должна пройти отдельную подающую ленту")
    if "fitPallet" in blocks and "stockPallets.inject(1)" not in code("fitPallet","onExit"):
        raise ValueError("Выданный запасной поддон должен пополняться")
    return True
