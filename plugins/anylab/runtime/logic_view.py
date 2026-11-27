"""Fit the native AnyLogic flowchart to a presentation area for recording."""

from pathlib import Path

from bridge.anylogic import field, put
from conveyor import by_name
from models import child, children, load


def add_logic_view(editor):
    main=editor.main
    areas=child(main,"Areas")
    if areas is None:
        areas=main.appendChild(editor.doc.createElement("Areas"))
    views=by_name(areas,"Area")
    prototype=next(iter(views.values()),None)
    if prototype is None:
        _,model=load(Path(__file__).with_name("templates")/"models/6.1/1/Model.alp")
        proto_main=by_name(child(model,"ActiveObjectClasses"),"ActiveObjectClass")["Main"]
        prototype=by_name(child(proto_main,"Areas"),"Area")["view2D"]
    view=editor.clone(prototype,"anylabBlockDiagram")
    blocks=children(child(main,"EmbeddedObjects"),"EmbeddedObject")
    x=[float(field(block,"X")) for block in blocks]
    y=[float(field(block,"Y")) for block in blocks]
    for link in children(editor.connectors,"Connector"):
        ox,oy=(float(field(link,key)) for key in ("X","Y"))
        for point in children(child(link,"Points"),"Point"):
            x.append(ox+float(field(point,"X")))
            y.append(oy+float(field(point,"Y")))
    padding=max(115,(max(x)-min(x))*.025)
    lx,ly=min(x)-padding,min(y)-padding
    hx,hy=max(x)+padding,max(y)+padding
    original=views.get("viewAreaLogic")
    if original is not None:
        ox,oy,w,h=(float(field(original,key)) for key in ("X","Y","Width","Height"))
        lx,ly,hx,hy=min(lx,ox),min(ly,oy),max(hx,ox+w),max(hy,oy+h)
    for key,value in {"X":lx,"Y":ly,"Width":hx-lx,"Height":hy-ly,"Title":"Блок-схема"}.items():
        put(view,key,str(value))
    areas.appendChild(view)
    return view
