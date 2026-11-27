"""Coordinate the metro presentation and pedestrian routing in both models."""

from bridge.anylogic import field, put
from conveyor import by_name, set_param
from models import child, children, set_points


def add_boarding(scene,editor,side_platforms=False):
    lines=by_name(scene,"TargetLine")
    cars=by_name(scene,"Figure3D")
    for direction,car_range,side in ((1,range(1,9),-1),(2,range(9,17),1)):
        if side_platforms:
            side=-side
        wait=f"pedWaitTrain{direction}"
        sink=f"pedSink{direction}"
        route=f"pedBoardTrain{direction}"
        outside,inside=[],[]
        for car_index in car_range:
            car=cars[f"subway_car_open{car_index}"]
            car_x,car_y=(float(field(car,key)) for key in ("X","Y"))
            for door,offset in enumerate((-62,-18,27,72)):
                for prefix,y,targets in (("Door",car_y-side*22,outside),("Inside",car_y+side*7,inside)):
                    name=f"targetTrain{prefix}{car_index}_{door}"
                    line=editor.clone(lines[f"targetEntryTrain{direction}"],name)
                    put(line,"X",str(car_x+offset-5)); put(line,"Y",str(y))
                    set_points(line,[(0,0,0),(10,0,0)])
                    scene.appendChild(line)
                    targets.append(name)

        def assigned(targets):
            # All three blocks use the same stable door index for a passenger.
            return "(new TargetLine[]{"+",".join(targets)+"})[Math.floorMod(ped.getId(),"+str(len(targets))+")]"

        car=cars[f"subway_car_open{3 if direction==1 else 14}"]
        car_x,car_y=(float(field(car,key)) for key in ("X","Y"))
        camera=by_name(scene,"Camera3D").get(f"cameraTrains{direction}")
        if camera is not None:
            for key,value in {"X":car_x-175,"Y":car_y-side*155,"Z":91,
                              "RotationX":23,"RotationZ":side*41}.items():
                put(camera,key,str(value))
        set_param(editor.blocks[f"pedGoToTrain{direction}"],"locationLine",assigned(outside))
        set_param(editor.blocks[wait],"locationLine",assigned(outside))
        set_param(editor.blocks[wait],"delayTimeout","triangular(0.15, 0.25, 0.35)")
        previous=editor.blocks[wait]
        x=round((float(field(previous,"X"))+float(field(editor.blocks[sink],"X")))/2)
        y=round((float(field(previous,"Y"))+float(field(editor.blocks[sink],"Y")))/2)-44
        editor.block(editor.blocks[f"pedGoToTrain{direction}"],route,x,y,
                     {"locationLine":assigned(inside)})
        for link in children(editor.connectors,"Connector"):
            ends={field(child(link,key+"EmbeddedObjectReference"),"ItemName") for key in ("Source","Target")}
            if ends=={wait,sink}:
                editor.connectors.removeChild(link)
                break
        editor.connect(wait,route,(20,0),(-20,0))
        editor.connect(route,sink,(20,0),(-20,0))


def camera_panel(main, scene, part, editor, reference, opaque):
    cameras=by_name(scene,"Camera3D")
    window=next(node for node in children(scene,"Control") if node.getAttribute("Type")=="Window3D")
    reference_scene=child(reference,"Presentation/Level/Presentation")
    areas=child(main,"Areas")
    if part=="4.1":
        if areas is None:
            areas=main.appendChild(editor.doc.createElement("Areas"))
        for name,area in by_name(child(reference,"Areas"),"Area").items():
            if name!="viewAreaLogic":
                areas.appendChild(editor.clone(area))
        put(window,"X","5540"); put(window,"Y","40")
        prototype=next(node for node in reference.getElementsByTagName("Group") if field(node,"Name")=="camerasGroup")
        group=editor.clone(prototype)
        put(group,"X","5370"); put(group,"Y","1010")
        scene.appendChild(group)
        presentation=child(group,"Presentation")
        for node in children(presentation):
            name=field(node,"Name")
            if node.tagName=="Image" or name=="text1" or name in {f"button{i}" for i in range(6,11)}:
                presentation.removeChild(node)
            elif name in {"rectangle","rectangle1"}:
                put(node,"Width","760")
            elif name=="text2":
                put(node,"X","-825")
        for source in children(reference_scene,"Camera3D"):
            name=field(source,"Name")
            if name.startswith(("cameraHall","cameraEntry","cameraTrains")):
                scene.appendChild(editor.clone(source))
        view=by_name(areas,"Area")["viewArea3D"]
        for k,v in {"X":4360,"Y":-120,"Width":4660,"Height":2510}.items():
            put(view,k,str(v))
        control=editor.clone(children(presentation,"Control")[0],"metroOpenCameras")
        put(control,"X","180"); put(control,"Y","25")
        put(child(control,"BasicProperties"),"ActionCode","viewArea3D.navigateTo();")
        put(child(control,"ExtendedProperties"),"LabelText","Управление камерами")
        scene.appendChild(control)
        back=editor.clone(control,"metroReturnToPlan")
        put(back,"X","-784"); put(back,"Y","430")
        put(child(back,"BasicProperties"),"ActionCode","viewArea2D.navigateTo();")
        put(child(back,"ExtendedProperties"),"LabelText","Вернуться к 2D-плану")
        presentation.appendChild(back)
    else:
        group=next(node for node in main.getElementsByTagName("Group") if field(node,"Name")=="camerasGroup")
        if opaque:
            for name,pose in {"cameraSMFloors":(3208,-422,26,5,27),
                              "cameraSMIn":(3790,-398,25,4,149),
                              "cameraSMBack":(3765,-121,26,6,-143)}.items():
                for key,value in zip(("X","Y","Z","RotationX","RotationZ"),pose):
                    put(cameras[name],key,str(value))
            put(child(by_name(child(group,"Presentation"),"Control")["button7"],"ExtendedProperties"),
                "LabelText","Камера 8: галерея изнутри")
            put(child(by_name(child(group,"Presentation"),"Control")["button9"],"ExtendedProperties"),
                "LabelText","Камера 10: вход изнутри")

    names={"button":"Вестибюль 1","button1":"Вестибюль 2","button2":"Входы 1",
           "button3":"Входы 2","button4":"Посадка · путь 1","button5":"Посадка · путь 2"}
    for button in children(child(group,"Presentation"),"Control"):
        name=field(button,"Name")
        if name in names:
            put(child(button,"ExtendedProperties"),"LabelText",names[name])
