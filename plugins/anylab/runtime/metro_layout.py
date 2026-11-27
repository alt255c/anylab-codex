"""Build station-specific passage networks and draw the matching passenger plans."""

from bridge.anylogic import field, put
from conveyor import by_name, set_param
from models import child, children, set_points


# Street portals are ordered east and west from the platform. Each describes
# a continuous corridor from a concourse to the point where passengers enter.
LAYOUTS = {
    "tsaritsyno": ("island", (
        ("Товарищеская улица", ((3480,900),(3480,510),(3770,510))),
        ("Каспийская улица", ((3260,900),(3260,430))),
        ("МЦД D2", ((3530,1260),(3530,1570),(3740,1570))),
    ), (
        ("Весёлая улица", ((650,1060),(650,540),(440,540))),
        ("Кавказский бульвар", ((455,1220),(455,1800))),
        ("Каспийская улица", ((260,1140),(100,1140),(100,1530))),
    )),
    "kashirskaya": ("interchange", (
        ("Каширское шоссе", ((3560,900),(3560,290))),
        ("ТРК «Москворечье»", ((3300,890),(3300,490),(3020,490))),
    ), (
        ("Проспект Андропова", ((330,1230),(330,1770))),
        ("Парк «Садовники»", ((580,1240),(580,1590),(795,1590))),
    )),
    "klenovy_bulvar": ("side", (
        ("Коломенская улица", ((3310,920),(3310,420),(3060,420))),
        ("Кленовый бульвар", ((3510,920),(3510,240))),
        ("Музей-заповедник «Коломенское»", ((3650,1220),(3650,1540))),
    ), ()),
    "kolomenskaya": ("island", (
        ("Проспект Андропова", ((3460,920),(3460,480),(3620,480),(3620,225))),
        ("Музей-заповедник «Коломенское»", ((3310,920),(3310,380),(3060,380))),
        ("Нагатинская набережная", ((3410,1190),(3410,1730),(3710,1730))),
        ("ТЦ «Коломенский»", ((3640,1190),(3640,1460),(3790,1460))),
    ), (
        ("Нагатинская улица", ((450,910),(450,440),(150,440))),
        ("Нагатинская улица", ((675,910),(675,590),(830,590))),
        ("Улица Высокая", ((340,1230),(340,1900),(135,1900))),
        ("Проспект Андропова", ((615,1230),(615,1600),(835,1600))),
    )),
    "nagatinsky_zaton": ("side", (
        ("Коломенская улица", ((3600,935),(3600,475),(3730,475))),
    ), ()),
}

PORTAL_NUMBERS={"kolomenskaya":(1,2,7,8,3,4,6,5)}


def position(node, x, y):
    put(node,"X",str(x)); put(node,"Y",str(y))


def move_line(line, start, end):
    position(line,*start)
    set_points(line,[(0,0,0),(end[0]-start[0],end[1]-start[1],0)])


def boundary(rectangles, openings):
    xs=sorted({x for l,_,r,_ in rectangles for x in (l,r)})
    ys=sorted({y for _,t,_,b in rectangles for y in (t,b)})
    cells={(i,j) for i,x in enumerate(xs[:-1]) for j,y in enumerate(ys[:-1])
           if any(l<=x<r and t<=y<b for l,t,r,b in rectangles)}
    for i,j in sorted(cells):
        l,r=xs[i:i+2]; t,b=ys[j:j+2]
        for neighbor,edge in (((i-1,j),((l,t),(l,b))),((i+1,j),((r,t),(r,b))),
                              ((i,j-1),((l,t),(r,t))),((i,j+1),((l,b),(r,b)))):
            if neighbor in cells:
                continue
            axis=0 if edge[0][0]==edge[1][0] else 1
            if any(all(p[axis]==a[axis] and a[1-axis]<=p[1-axis]<=z[1-axis] for p in edge)
                   for a,z in openings if a[axis]==z[axis]):
                continue
            yield edge


def install_layout(scene, editor, station):
    kind,east,west=LAYOUTS[station]
    rectangles=[(2920,715,3735,1380),(1050 if not west else 860,735,3050,1390)]
    if west:
        rectangles.append((185,735,965,1390))
    openings=[]
    portals=[]
    line_bounds=[]
    for label,path in east+west:
        width=55
        for (x,y),(nx,ny) in zip(path,path[1:]):
            if x==nx:
                rectangles.append((x-width,min(y,ny),x+width,max(y,ny)))
            else:
                rectangles.append((min(x,nx),y-width,max(x,nx),y+width))
        for x,y in path[1:-1]:
            rectangles.append((x-width,y-width,x+width,y+width))
        (px,py),(x,y)=path[-2:]
        if x==px:
            opening=((x-width,y),(x+width,y))
            y_in=y+18*(1 if py>y else -1)
            target=((x-36,y_in),(x+36,y_in))
        else:
            opening=((x,y-width),(x,y+width))
            x_in=x+18*(1 if px>x else -1)
            target=((x_in,y-36),(x_in,y+36))
        openings.append(opening)
        line_bounds.append(target)
        portals.append((label,opening))

    walls=by_name(scene,"Wall")
    prototype=walls["wall"]
    for name in ("wall","wall1","wall2","wall3","wall4","wall5"):
        scene.removeChild(walls[name])
    outline=list(boundary(rectangles,openings))
    if kind=="side":
        outline.append(((1100,1050),(2820,1050)))
        for car in by_name(scene,"Figure3D").values():
            name=field(car,"Name")
            if not name.startswith("subway_car_open"):
                continue
            upper=int(name.removeprefix("subway_car_open"))<=8
            for element in car.getElementsByTagName("Y"):
                if element.parentNode is car:
                    element.firstChild.data=str(980 if upper else 1120)
            put(car,"Rotation","0" if upper else "180")
    for i,(start,end) in enumerate(outline):
        wall=editor.clone(prototype,f"metroPassageWall{i}")
        position(wall,*start)
        d=(end[0]-start[0],end[1]-start[1],0)
        set_points(wall,[(0,0,0)]*3+[d]*3)
        scene.appendChild(wall)

    lines=by_name(scene,"TargetLine")
    def assign_group(numbers, indices):
        for i,n in enumerate(numbers):
            bounds=line_bounds[indices[i%len(indices)]]
            for label in ("Entry","Exit"):
                move_line(lines[f"target{label}{n}"],*bounds)

    east_ids=list(range(len(east)))
    west_ids=list(range(len(east),len(portals)))
    assign_group((1,2,3),east_ids)
    assign_group((4,5,6),west_ids or east_ids)
    cameras=by_name(scene,"Camera3D")
    for name,pose in {"cameraEntrySide1":(495,790,150,38,53) if west else (3500,792,150,38,113),
                      "cameraEntrySide2":(3460,812,148,38,119)}.items():
        if name in cameras:
            for key,value in zip(("X","Y","Z","RotationX","RotationZ"),pose):
                put(cameras[name],key,str(value))
    if not west:
        side_select=editor.blocks["pedSelectSide"]
        set_param(side_select,"probability1","1.0")
        set_param(side_select,"probability2","0.0")
        for link in children(editor.connectors,"Connector"):
            source=child(link,"SourceEmbeddedObjectReference")
            target=child(link,"TargetEmbeddedObjectReference")
            endpoints={field(source,"ItemName"),field(target,"ItemName")}
            if "checkDetectorsSide1" in endpoints and endpoints.intersection({f"inEntry{i}Source" for i in (4,5,6)}):
                put(source if field(source,"ItemName")=="checkDetectorsSide1" else target,"ItemName","checkDetectorsSide2")
        if "cameraHallSide1" in cameras:
            position(cameras["cameraHallSide1"],3480,1050)
        for shape in children(scene):
            if shape.tagName not in {"Wall","Figure3D"}:
                continue
            x=float(field(shape,"X"))
            if x>=990:
                continue
            if shape.tagName=="Wall":
                if field(shape,"Name") in {"wall6","wall7","wall10","wall11","wall12"}:
                    scene.removeChild(shape)
            else:
                scene.removeChild(shape)

    for n,index in ((3,3),(6,7)) if len(portals)==8 else ():
        for label,block in (("Entry",f"inEntry{n}Source"),("Exit",f"pedGoToExit{n}")):
            original=f"target{label}{n}"
            extra=f"metro{label}{index+1}"
            line=editor.clone(lines[original],extra)
            move_line(line,*line_bounds[index]); scene.appendChild(line)
            set_param(editor.blocks[block],"locationLine",f"randomTrue(0.5) ? {original} : {extra}")

    if kind=="side":
        for n,y in ((1,951),(2,1149)):
            move_line(lines[f"targetExitTrain{n}"],(1140,y),(2740,y))
    numbers=PORTAL_NUMBERS.get(station,range(1,len(portals)+1))
    return kind, rectangles, outline, list(zip(numbers,portals))


def draw_plan(layout, name, accent):
    from PIL import Image, ImageDraw, ImageFont

    kind,rectangles,outline,portals=layout
    width,height=1900,1100
    image=Image.new("RGB",(width,height),"#FFFFFF")
    draw=ImageDraw.Draw(image)
    def scaled(point):
        return tuple(round(value/2) for value in point)
    try:
        font=ImageFont.truetype("DejaVuSans.ttf",29)
    except OSError:
        font=ImageFont.truetype("arial.ttf",29)
    small=font.font_variant(size=17)
    for l,t,r,b in rectangles:
        draw.rectangle((scaled((l,t)),scaled((r,b))),fill="#EBF2F0")
    floors={
        "island":((870,1222,"Островная платформа"),),
        "side":((775,951,"Платформа 1"),(1149,1345,"Платформа 2")),
        "interchange":((790,823,"Зал 1"),(1285,1338,"Зал 2")),
    }
    for top,bottom,label in floors[kind]:
        draw.rectangle((scaled((1115,top)),scaled((2780,bottom))),fill="#CEE0DC")
        draw.text(scaled((1947,(top+bottom)/2)),label,font=small,fill="#335354",anchor="mm")
    train_y=(980,1120) if kind=="side" else (840,1265)
    if kind=="interchange":
        for y in (770,1360):
            draw.rectangle((scaled((1115,y-13)),scaled((2780,y+13))),fill="#7B8B91")
    for y in train_y:
        draw.rectangle((scaled((1115,y-16)),scaled((2780,y+16))),fill=accent)
        for x in range(1160,2770,187):
            draw.line((scaled((x,y-5)),scaled((min(x+145,2770),y-5))),fill="#FFFFFF",width=2)
    if kind=="side":
        for x in (1075,2865):
            for offset in (-12,-6,0,6,12):
                draw.line((scaled((x+offset,935)),scaled((x+offset,1165))),fill="#A5B9B4",width=2)
    draw.text(scaled((3350,1050)),"Вестибюль" if rectangles[1][0]==1050 else "Вестибюль 1",
              font=small,fill="#335354",anchor="mm")
    if rectangles[1][0]!=1050:
        draw.text(scaled((565,1050)),"Вестибюль 2",font=small,fill="#335354",anchor="mm")
    for start,end in outline:
        draw.line((scaled(start),scaled(end)),fill="#335354",width=2)
    for number,(label,(start,end)) in portals:
        a,b=scaled(start),scaled(end)
        draw.line((a,b),fill=accent,width=6)
        x,y=(a[0]+b[0])/2,(a[1]+b[1])/2
        y+=18 if y>height/2 else -18
        draw.rounded_rectangle((x-13,y-11,x+13,y+11),radius=4,fill="#203D40")
        draw.text((x,y),str(number),font=small,fill="white",anchor="mm")
        tx=max(12,min(width-12-small.getlength(label),x+19))
        draw.text((tx,y+16),label,font=small,fill="#203D40",anchor="lm")
    draw.text((width/2,85),name,font=font,fill="#203D40",anchor="mm")
    details={"side":"Береговые платформы","island":"Островная платформа",
             "interchange":"Две островные платформы · пересадка между линиями"}
    draw.text((width/2,120),details[kind],font=small,fill="#203D40",anchor="mm")
    return image
