"""Stage the open four-dispenser example with queue admission and driver payment."""
from pathlib import Path
import shutil

from bridge.anylogic import put
from models import load,children,child,field
from conveyor import LineEditor,by_name,set_param,tutorial,place
from projects import copy_resources


def build_gas_station(destination,payment=False):
    from anylab import examples
    source=Path(next(p for p in examples("Gas Station") if Path(p).stem=="Gas Station"))
    d,m=load(source);main=by_name(child(m,"ActiveObjectClasses"),"ActiveObjectClass")["Main"]
    editor=LineEditor(d,m,main)
    template_path=Path(__file__).parent/"templates/models/5.2/1/ConveyorLine.alp"
    _,cargo_model=load(template_path)
    cargo_main=by_name(child(cargo_model,"ActiveObjectClasses"),"ActiveObjectClass")["Main"]
    cargo_blocks=by_name(child(cargo_main,"EmbeddedObjects"),"EmbeddedObject")
    package=field(cargo_model,"JavaPackageName")
    prototype=by_name(child(cargo_main,"Variables"),"Variable")["assembled"]
    for name,kind,value in (("arrived","int","0"),("served","int","0"),("bypassed","int","0"),("paid","int","0"),("returnedDrivers","int","0"),("stationTimeTotal","double","0")):
        editor.variable(main,prototype,name,value,1000,kind)
    parameter=by_name(child(cargo_main,"Variables"),"Variable")["ИнтенсивностьПрибытия"]
    for name,value in (("arrivalIntensity","2.5"),("queueLimit","8")):
        var=editor.clone(parameter,name,package);put(child(var,"Properties/DefaultValue"),"Code",value);child(main,"Variables").appendChild(var)
    set_param(editor.blocks["carSource"],"rate","arrivalIntensity")
    car=by_name(child(m,"ActiveObjectClasses"),"ActiveObjectClass")["Car"]
    carvar=prototype
    editor.variable(car,carvar,"stationEntry","0",200,"double")
    editor.variable(car,carvar,"pumpNumber","0",250,"int")
    set_param(editor.blocks["carSource"],"onExit","arrived++; car.stationEntry=time();"+(" car.setColor(car.fuelType==FuelType.GAS92 ? yellow : car.fuelType==FuelType.GAS95 ? blue : red);" if payment else ""))
    set_param(editor.blocks["carDeparture"],"onEnter","if(car.pumpNumber>0) { served++; stationTimeTotal+=time()-car.stationEntry; }")
    bypass=editor.block(cargo_blocks["selectWay"],"admitCar",150,-1240,{"condition":"seizeDispenser.size()>=queueLimit","onExitTrue":"bypassed++;"},package)
    for n in bypass.getElementsByTagName("GenericParameterSubstituteValue"):
        if field(n,"Code")=="Carton":put(n,"Code","Car")
    editor.unlink("toStationEntry","seizeDispenser")
    editor.connect("toStationEntry","admitCar",(40,10),(0,10))
    # SelectOutput requires explicit outT/outF; these are semantic ports.
    def connect(source,target,port="out",target_port="in"):
        editor.connect(source,target,(40,10),(0,10),target_port=target_port)
        n=children(editor.connectors,"Connector")[-1];put(child(n,"SourceConnectableItemReference"),"ItemName",port)
    connect("admitCar","leaveStation","outT");connect("admitCar","seizeDispenser","outF")
    for index in range(1,5):
        dispenser=by_name(child(m,"ActiveObjectClasses"),"ActiveObjectClass")["FuelDispenser"]
        # One shared type: the instance parameter number identifies the pump.
        for b in children(child(dispenser,"EmbeddedObjects"),"EmbeddedObject"):
            if field(b,"Name")=="carMoveTo":set_param(b,"onEnter","car.pumpNumber=number;")
    road_example=Path(examples("Road Traffic Tutorial - Phase 6")[0]);_,road_model=load(road_example)
    road_main=by_name(child(road_model,"ActiveObjectClasses"),"ActiveObjectClass")["Main"]
    descriptor=by_name(child(road_main,"EmbeddedObjects"),"EmbeddedObject")["roadNetworkDescriptor"]
    editor.block(descriptor,"roadNetworkDescriptor",40,-1200,package=field(road_model,"JavaPackageName"))
    if payment:
        # Drivers use ordinary Agent movement through MoveTo. Cars remain on
        # their road and hold their dispenser until their own driver returns.
        carton=by_name(child(cargo_model,"ActiveObjectClasses"),"ActiveObjectClass")["Carton"]
        driver=editor.clone(carton,"Driver",package)
        for tag in ("Variables","Presentation","Functions"):
            node=child(driver,tag)
            if node is not None:
                while node.firstChild:node.removeChild(node.firstChild)
        put(driver,"StartupCode","")
        put(driver,"FlowChartsUsage","ENTITY")
        child(m,"ActiveObjectClasses").appendChild(driver)
        editor.variable(driver,prototype,"car","null",0,"Car")
        editor.variable(driver,prototype,"cashier","0",50,"int")
        # Simple readable person geometry in 2D and 3D.
        presentation=child(driver,"Presentation")
        source_pres=child(carton,"Presentation")
        for node in children(source_pres):presentation.appendChild(d.importNode(node,True))
        shapes=child(driver,"Presentation/Level/Presentation")
        while shapes.firstChild:shapes.removeChild(shapes.firstChild)
        # A штатный person object, with its included 2D preview.
        worker=next(n for n in cargo_main.getElementsByTagName("Figure3D") if field(n,"Name")=="worker")
        human=editor.clone(worker,"person",package);place(human,0,0);shapes.appendChild(human)
        put(child(driver,"AgentProperties/VelocityCode"),"Code","1.4")
        editor.variable(main,prototype,"pendingDrivers","new java.util.ArrayDeque<Car>()",1000,"java.util.ArrayDeque<Car>")
        delay=cargo_blocks["storeBox"]
        def typed(proto,name,x,y,params,kind):
            b=editor.block(proto,name,x,y,params,package)
            for node in b.getElementsByTagName("ClassName"):
                if field(node.parentNode,"ClassName")=="Carton":put(node.parentNode,"ClassName",kind)
            for node in b.getElementsByTagName("GenericParameterSubstituteValue"):
                if field(node,"Code")=="Carton":put(node,"Code",kind)
            return b
        wait=typed(delay,"waitForDriver",1000,-1030,{"type":"self.MANUAL","maximumCapacity":"true","onEnter":"pendingDrivers.addLast((Car)agent); driverSource.inject(1);"},"Car")
        for i in range(1,5):
            editor.unlink("fuelDispenser"+str(i),"releaseDispenser")
            connect("fuelDispenser"+str(i),"waitForDriver","carExit")
        connect("waitForDriver","releaseDispenser")
        src=typed(cargo_blocks["partSource"],"driverSource",200,-920,{"onAtExit":"agent.car=pendingDrivers.removeFirst(); agent.cashier=agent.car.pumpNumber<=2 ? 0 : 1; agent.setXY(agent.car.getX()-18,agent.car.getY());","onExit":""},"Driver")
        set_param(src,"locationX","0");set_param(src,"locationY","0");set_param(src,"changeDimensions","false")
        _,exit_model,exit_main=tutorial("ConveyorExit")
        move=by_name(child(exit_main,"EmbeddedObjects"),"EmbeddedObject")["toStorage"]
        ex_package=field(exit_model,"JavaPackageName")
        for name,x,destx,desty in (("walkToCashier",340,"440","agent.cashier==0 ? 345 : 530"),("returnToCar",1000,"agent.car.getX()-18","agent.car.getY()")):
            b=typed(move,name,x,-920,{"destinationType":"self.DEST_XYZ","destinationX":destx,"destinationY":desty,"destinationZ":"0","destinationInNetwork":"false","straightMovement":"true","setSpeed":"true","speed":"1.4"},"Driver")
            # Imported MoveTo's generic refs use its tutorial package.
            for node in b.getElementsByTagName("PackageName"):
                if field(node.parentNode,"PackageName")==ex_package:put(node.parentNode,"PackageName",editor.package)
        choose=typed(cargo_blocks["selectWay"],"chooseCashier",480,-920,{"condition":"agent.cashier==0"},"Driver")
        _,enter_model,enter_main=tutorial("ConveyorEnter")
        queue=by_name(child(enter_main,"EmbeddedObjects"),"EmbeddedObject")["palletBuffer1"]
        for i,y in ((0,-920),(1,-790)):
            q=typed(queue,"payQueue"+str(i),620,y,{},"Driver")
            for node in q.getElementsByTagName("PackageName"):
                if field(node.parentNode,"PackageName")==field(enter_model,"JavaPackageName"):put(node.parentNode,"PackageName",editor.package)
            typed(delay,"payment"+str(i),800,y,{"type":"self.TIMEOUT","delayTime":"uniform(15,30)","maximumCapacity":"false","capacity":"1","onExit":"paid++;"},"Driver")
        typed(cargo_blocks["sink"],"driverReturned",1170,-920,{"onEnter":"returnedDrivers++; waitForDriver.stopDelay(agent.car);"},"Driver")
        connect("driverSource","walkToCashier");connect("walkToCashier","chooseCashier")
        connect("chooseCashier","payQueue0","outT");connect("chooseCashier","payQueue1","outF")
        for i in (0,1):connect("payQueue"+str(i),"payment"+str(i));connect("payment"+str(i),"returnToCar")
        connect("returnToCar","driverReturned")
        # Two visible cashier counters, one serving each pair of dispensers.
        rect=next(n for n in carton.getElementsByTagName("Rectangle") if field(n,"Name")=="carton2D")
        root_shapes=child(main,"Presentation/Level/Presentation")
        for i,y in enumerate((345,530)):
            n=editor.clone(rect,"cashierCounter"+str(i));place(n,410,y-14)
            for field_node in children(n,"FillColorCode"):n.removeChild(field_node)
            for key,val in {"Width":"34","Height":"28","Z":"0","ZHeight":"25","FillColor":"-14395444","VisibleCode":"true","DrawMode":"SHAPE_DRAW_2D3D"}.items():put(n,key,val)
            root_shapes.appendChild(n)
            editor.caption("cashierLabel"+str(i),"Оплата колонок "+("1–2" if i==0 else "3–4"),370,y-35)
    dest=Path(destination);dest.mkdir(parents=True,exist_ok=False)
    copy_resources(source,dest,False)
    if payment:
        copy_resources(template_path,dest,False)
        resource=next(r for r in children(child(cargo_model,"ModelResources"),"Resource") if field(r,"Path")=="3d/worker_2_m.glb")
        child(m,"ModelResources").appendChild(editor.clone(resource))
    name="GasStationPayment" if payment else "GasStation"
    put(m,"Name",name)
    ex=child(m,"Experiments/SimulationExperiment");put(ex,"SeedValue","73")
    put(child(ex,"PresentationProperties"),"ExecutionMode","virtualTime")
    put(child(ex,"ModelTimeProperties"),"StopOption","Stop at specified time");put(child(ex,"ModelTimeProperties"),"FinalTime","30")
    target=dest/(name+".alp");target.write_bytes(d.toxml(encoding="UTF-8"))
    return target
