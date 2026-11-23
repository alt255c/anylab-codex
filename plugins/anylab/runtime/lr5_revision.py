"""Separate the middle section from ConveyorEnter preparation and keep manual input manual."""
from pathlib import Path
from models import child, children, load
from bridge.anylogic import field, put
from conveyor import LineEditor, by_name, place, set_param


def param(block, key):
    p = by_name(child(block, 'Parameters'), 'Parameter').get(key)
    value=child(p,'Value') if p is not None else None
    return field(value,'Code') if value is not None else ''


def remove_block(editor, name):
    for link in list(children(editor.connectors, 'Connector')):
        if name in [field(child(link, side+'EmbeddedObjectReference'), 'ItemName') for side in ['Source','Target']]:
            editor.connectors.removeChild(link)
    node = editor.blocks.pop(name, None)
    if node is not None: editor.embedded.removeChild(node)


def connect(editor, a, b, port='in', source_port='out', bends=()):
    # Block origins are their top-left palette anchors, ports are relative to them.
    klass = field(child(editor.blocks[a], 'ActiveObjectClass'), 'ClassName')
    wide={'Queue','Delay','Seize','Release','MoveTo'}
    start = (30,10) if klass in ['Source','Combine'] else (40,10) if klass in ['Convey','ConveyorExit','ConveyorEnter'] else (40,20) if klass in wide else (20,10)
    if klass=='SelectOutput':start=(30,10) if source_port=='outT' else (20,20)
    target=field(child(editor.blocks[b],'ActiveObjectClass'),'ClassName')
    end = (10,10) if port=='in1' or target=='SelectOutput' else (10,30) if port=='in2' else (0,20) if target in wide else (0,10)
    x,y=float(field(editor.blocks[a],'X'))+start[0],float(field(editor.blocks[a],'Y'))+start[1]
    xx,yy=float(field(editor.blocks[b],'X'))+end[0],float(field(editor.blocks[b],'Y'))+end[1]
    if not bends and x!=xx and y!=yy:bends=((int(xx-40),int(y)),(int(xx-40),int(yy)))
    editor.connect(a,b,start,end,bends,port)
    link=children(editor.connectors,'Connector')[-1]
    put(child(link,'SourceConnectableItemReference'),'ItemName',source_port)


def revise(doc, model, main, full):
    editor=LineEditor(doc,model,main)
    # A perpetual UI event must not run in a parameter experiment: destroying
    # its root between iterations can otherwise loop in DynamicEvent.onDestroy.
    startup=field(main,'StartupCode').replace('\nnew AnyLabFixedTabs();',
        '\nif(getExperiment() instanceof com.anylogic.engine.ExperimentSimulation) new AnyLabFixedTabs();')
    put(main,'StartupCode',startup)
    set_param(editor.blocks['source1'],'arrivalType','self.MANUAL')
    rate=by_name(child(editor.blocks['source1'],'Parameters'),'Parameter')['rate']
    for old in children(rate,'Value'):rate.removeChild(old)
    # The button is the single public entry point for hand-assembled boxes.
    button=next(n for n in main.getElementsByTagName('Control') if n.getAttribute('Type')=='Button')
    put(child(button,'BasicProperties'),'ActionCode','source1.inject(1);')
    set_param(editor.blocks['source'],'onBeforeArrival',('sheetSource.inject(1); ' if full else '')+'partSource.inject(1);')
    initial=param(editor.blocks['source'],'onAtExit')
    initial=initial.replace('hasPalletSheet=false','hasPalletSheet='+('false' if full else 'true'))
    set_param(editor.blocks['source'],'onAtExit',initial)
    # A pallet is assembled with a sheet before the perpendicular part arrives.
    carton=by_name(child(model,'ActiveObjectClasses'),'ActiveObjectClass')['Carton']
    for shape in children(child(carton,'Presentation/Level/Presentation')):
        visible=field(shape,'VisibleCode')
        if '(cargoRole==0 || cargoRole==3)' in visible and 'hasAssemblyPart' not in visible:
            put(shape,'VisibleCode',visible.replace('(cargoRole==0 || cargoRole==3)','cargoRole==3'))
        # Tape and loose-part expressions already have their own sealed/assembly conditions.
        if field(shape,'Name').endswith(('carton2D','closedLid')) or 'box' in field(shape,'Name').lower() or 'flap' in field(shape,'Name'):
            put(shape,'VisibleCode',field(shape,'VisibleCode').replace('(cargoRole==0 || cargoRole==3)','cargoRole==3'))
    if full:
        if 'sheetTravel' not in editor.blocks:
            editor.block(editor.blocks['loadingTravel'],'sheetTravel',-50,400,{
                'sourceType':'self.SOURCE_CURRENT_POSITION','targetPositionOnConveyor':'assemblyJoin',
                'removeFromConveyor':'false','onExit':'palletsTravelled++;'})
        inlet=next(n for n in main.getElementsByTagName('Conveyor') if field(n,'Name')=='loadingBelt')
        if not any(field(n,'Name')=='sheetJoin' for n in inlet.getElementsByTagName('PositionOnConveyor')):
            prototype=next(n for n in inlet.getElementsByTagName('PositionOnConveyor') if field(n,'Name')=='assemblyJoin')
            pos=editor.clone(prototype,'sheetJoin');put(pos,'Offset','45');child(inlet,'Presentation').appendChild(pos)
        set_param(editor.blocks['loadingTravel'],'targetPositionOnConveyor','sheetJoin')
        set_param(editor.blocks['loadingTravel'],'onExit','')
        set_param(editor.blocks['fitSheet'],'onExit','agent.hasPalletSheet=true; agent.refreshCargo();')
    else:
        for name in ['stockPallets','palletStockBuffer','fitPallet','sheetSource','fitSheet','sheetTravel']:
            remove_block(editor,name)
        put(main,'StartupCode',field(main,'StartupCode').replace('stockPallets.inject(6);',''))
        for node in list(main.getElementsByTagName('*')):
            if field(node,'Name') in ['palletStaging','stockLabel'] and node.parentNode is not None:
                node.parentNode.removeChild(node)
        set_param(editor.blocks['loadingTravel'],'onExit','palletsTravelled++;')
    # Place the actual logical blocks below all spatial markup.
    locations={'source':(-650,900),'fitPallet':(-500,900),'loadingGate':(-350,900),
               'loadingTravel':(-200,900),'fitSheet':(-40,900),'sheetTravel':(120,900),
               'fitPart':(280,900),'fromConveyorStart':(440,900),'selectWay':(600,900),
               'toStation':(760,900),'toConveyorEnd':(940,900),'stockPallets':(-650,1010),
               'palletStockBuffer':(-500,1000),'sheetSource':(-200,1090),
               'partSource':(-200,1200),'partTravel':(120,1200),
               'source1':(380,1040),'manualTravel':(500,1040),'fromPosition':(620,1040),
               'seizeForklift':(1110,890),'leaveBelt':(1260,900),'toWarehouse':(1410,890),
               'releaseForklift':(1560,890),'storeBox':(1730,890),'sink':((1900 if full else 1110),900),
               'forklift':(1110,1030)}
    if not full:
        locations.update(source=(-200,900),loadingGate=(-40,900),loadingTravel=(120,900))
    for name,xy in locations.items():
        if name in editor.blocks:place(editor.blocks[name],*xy)
    for link in list(children(editor.connectors,'Connector')):editor.connectors.removeChild(link)
    row=(['source','fitPallet','loadingGate','loadingTravel','fitSheet','sheetTravel','fitPart'] if full else ['source','loadingGate','loadingTravel','fitPart'])+['fromConveyorStart','selectWay']
    for a,b in zip(row,row[1:]):connect(editor,a,b,'in1' if b in ['fitPallet','fitSheet','fitPart'] else 'in')
    if full:
        connect(editor,'stockPallets','palletStockBuffer')
        connect(editor,'palletStockBuffer','fitPallet','in2',bends=((-430,1020),(-430,960),(-490,960)))
        connect(editor,'sheetSource','fitSheet','in2',bends=((-30,1100),))
    connect(editor,'partSource','partTravel')
    connect(editor,'partTravel','fitPart','in2',bends=((290,1210),))
    connect(editor,'source1','manualTravel');connect(editor,'manualTravel','fromPosition')
    connect(editor,'fromPosition','selectWay',bends=((670,1050),(670,950),(560,950),(560,910)))
    connect(editor,'selectWay','toStation',source_port='outT')
    connect(editor,'selectWay','toConveyorEnd',source_port='outF',bends=((620,980),(900,980),(900,910)))
    connect(editor,'toStation','toConveyorEnd')
    row=['toConveyorEnd']+(['seizeForklift','leaveBelt','toWarehouse','releaseForklift','storeBox'] if full else [])+['sink']
    for a,b in zip(row,row[1:]):connect(editor,a,b)
    place(button,440,1130)
    # Internal variables/functions do not belong in a screenshot of the block flow.
    for tag in ['Variable','Function']:
        for n in main.getElementsByTagName(tag):put(n,'PresentationFlag','false')
    return main


def add_variation(doc,model,main,full):
    if any(field(e,'Name')=='Capacity' for e in children(child(model,'Experiments'))):return
    editor=LineEditor(doc,model,main)
    _,proto=load(Path(__file__).parent/'templates/models/2.2/1/Model.alp')
    original=next(e for e in children(child(proto,'Experiments')) if e.tagName=='ParamVariationExperiment')
    experiment=editor.clone(original,'Capacity')
    experiment.setAttribute('ActiveObjectClassId',field(main,'Id'))
    for tag in ['FreeformParamValue','RangeVariationParamValue']:
        for n in children(experiment,tag):experiment.removeChild(n)
    variables=child(experiment,'Variables')
    for n in list(children(variables)):variables.removeChild(n)
    analysis=child(experiment,'AnalysisData');dataset=children(analysis,'DataSet')[0]
    for n in list(children(analysis)):
        if n is not dataset:analysis.removeChild(n)
    put(dataset,'Name','throughputData')
    put(dataset,'PresentationFlag','false')
    pres=child(experiment,'Presentation');plot=children(pres,'Plot')[0]
    for n in list(children(pres)):
        if n is not plot:pres.removeChild(n)
    put(plot,'Name','throughputPlot');place(plot,50,70)
    put(plot,'AutoUpdate','false')
    put(plot,'Width','850');put(plot,'Height','470')
    for k,v in {'XOffset':70,'YOffset':45,'Width':700,'Height':330}.items():put(child(plot,'ChartArea'),k,str(v))
    series=plot.getElementsByTagName('DatasetExpression')
    first=series[0]
    for n in list(series)[1:]:n.parentNode.removeChild(n)
    put(first,'Title','Производительность, коробок/мин');put(first,'Expression','throughputData')
    put(first,'Color',str(-14129235));put(first,'LineWidth','2.5')
    put(plot,'HorScaleFromExpression','0');put(plot,'HorScaleToExpression','32')
    for n in plot.getElementsByTagName('*'):
        if n.firstChild and n.firstChild.nodeType in [3,4]:
            if n.firstChild.data in ['P1','Вероятность отказа','Пропускная способность']:
                n.firstChild.data='Интенсивность подачи, коробок/мин' if n.firstChild.data=='P1' else 'Производительность, коробок/мин'
    put(experiment,'BeforeEachExperimentRunCode','throughputData.reset();')
    output='root.ordinaryDelivered+root.fragileDelivered' if full else 'root.sink.count()'
    put(experiment,'AfterSimulationRunCode','throughputData.add(root.ИнтенсивностьПрибытия, ('+output+')*60.0/900.0);')
    put(experiment,'AfterExperimentCode','')
    put(experiment,'AllowParallelEvaluations','false');put(experiment,'UseFreeformParameters','false')
    put(experiment,'SeedValue','73')
    parameter=by_name(child(main,'Variables'),'Variable')['ИнтенсивностьПрибытия']
    row=experiment.appendChild(doc.createElement('RangeVariationParamValue'))
    put(row,'Id',field(parameter,'Id'));put(row,'Type','RANGE')
    for name,value in [('From','4'),('To','28'),('Step','4')]:
        entry=row.appendChild(doc.createElement(name));entry.setAttribute('Class','CodeValue');put(entry,'Code',value)
    put(child(experiment,'ModelTimeProperties'),'FinalTime','900')
    put(child(experiment,'PresentationProperties'),'Title','Производительность конвейера')
    put(child(experiment,'ReplicationsProperties'),'UseReplication','false')
    child(model,'Experiments').appendChild(experiment)
