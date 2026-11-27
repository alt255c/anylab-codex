"""Keep the station plan legible and the three driveway mouths continuous."""
from bridge.anylogic import field, put
from conveyor import LineEditor, by_name
from models import child, children, set_points, xyz


def fix_station_layout(doc, model, main):
    scene=child(main,"Presentation/Level/Presentation")
    shapes=by_name(scene,"Rectangle")
    texts=by_name(scene,"Text")
    if "городскаяУлица" not in shapes:
        return
    editor=LineEditor(doc,model,main)
    # The station already has under-canopy lighting. The roadside fixtures
    # inherited from the forecourt prototype intersect the approach lanes.
    for name,shape in shapes.items():
        if name.startswith(("световаяОпора","световаяПланка")):
            scene.removeChild(shape)
    arrival=by_name(child(main,"EmbeddedObjects"),"EmbeddedObject")["прибытиеАвтомобилей"]
    parameters=by_name(child(arrival,"Parameters"),"Parameter")
    for name,acceleration in (("maxAcceleration",5),("maxDeceleration",7)):
        parameter=parameters[name]
        value=child(parameter,"Value")
        if value is None:
            value=parameter.appendChild(doc.createElement("Value"))
        value.setAttribute("Class","CodeUnitValue")
        put(value,"Code",str(acceleration))
        put(value,"Unit","MPS_SQ")
        child(value,"Unit").setAttribute("Class","AccelerationUnits")
    if "anylabPumpPanel" not in shapes:
        for number in (*range(15,45),53,54):
            label=texts[f"text{number}"]
            put(label,"Y",str(float(field(label,"Y"))+126))
    for number in (11,12,13,14,45):
        put(texts[f"text{number}"],"Y","91")
    put(texts["fuelLegend"],"Y","889")
    put(texts["fuelLegend"],"Color","-14468004")
    for name in ("подписьПереключателя",):
        put(texts[name],"Y","79")
    if "переключательПлотности" in shapes:
        put(shapes["переключательПлотности"],"Y","73")

    def plane(name,x,y,width,height,z,color,mode,anchor):
        node=editor.clone(shapes["городскаяУлица"],name)
        for key,value in dict(X=x,Y=y,Width=width,Height=height,Z=z,ZHeight=.06,
                              DrawMode=mode,FillColor=str(int(color,16)-2**24)).items():
            put(node,key,str(value))
        scene.insertBefore(node,anchor)

    panel_anchor=texts["text15"]
    if "anylabPumpPanel" not in shapes:
        plane("anylabPumpPanel",-40,799,1240,88,-.2,"394E5D","SHAPE_DRAW_2D",panel_anchor)
    else:
        put(shapes["anylabPumpPanel"],"Height","88")
    put(shapes["rectangle1"],"FillColor",str(int("37434A",16)-2**24))
    for name in ("Въезд","Выезд","Объезд"):
        node=shapes.get("anylabDriveway"+name)
        if node is not None:
            scene.removeChild(node)
    roads = {field(road,"Name"):road for road in main.getElementsByTagName("Road")}
    def straight(road,start,end):
        delta=tuple((b-a)/3 for a,b in zip(start,end))
        def handle(point,direction):
            return tuple(p+direction*d for p,d in zip(point,delta))
        set_points(road,[start,handle(start,-1),handle(start,1),
                         end,handle(end,-1),handle(end,1)])

    # The first endpoint belongs to SourceId. Listing the street end first
    # makes the generated junction connector send cars back toward the station.
    road=roads["roadExit"]
    straight(road,(0,0,0),(0,746-float(field(road,"Y")),0))
    for name in ("road6","road7"):
        road=roads[name]
        points=[xyz(point) for point in children(child(road,"Points"),"Point")]
        straight(road,points[0],points[-3])

    # Extend the existing network lanes at their free ends. Intersection anchors remain in place.
    for name, at_start in (("road",True),("полосаОбъезда",False)):
        road=roads[name]
        points=[xyz(point) for point in children(child(road,"Points"),"Point")]
        terminal=points[0 if at_start else -3]
        y=746-float(field(road,"Y"))
        x,base_y,z=terminal
        if abs(base_y-y)<.001:
            continue
        delta=(y-base_y)/3
        if at_start:
            # Reuse the old outward handle to preserve the original tangent at the merge.
            points=[(x,y,z),(x,y+delta,z),(x,y-delta,z),*points]
            for stop in road.getElementsByTagName("RoadStopline"):
                put(stop,"Offset",str(float(field(stop,"Offset"))+abs(y-base_y)))
        else:
            points.extend([(x,y,z),(x,y-delta,z),(x,y+delta,z)])
        set_points(road,points)
    for name in ("СевернаяСтена","ЮжнаяСтена","СтенаПавильона"):
        if name in shapes:
            put(shapes[name],"ZHeight","42")
    old_roof=shapes.get("КозырёкПавильона")
    if old_roof is not None:
        scene.removeChild(old_roof)
    for name,position in (("view2D",(-50,0,1280,925)),):
        area=by_name(child(main,"Areas"),"Area").get(name)
        if area is not None:
            for axis,value in zip(("X","Y","Width","Height"),position):
                put(area,axis,str(value))
