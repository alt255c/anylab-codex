"""Inspect and transform AnyLogic 8 XML projects with the Python standard library.

Public functions operate on a single ALP. projects.py stages its resources. Keys
are based on the original owner and element names, for example Main.conveyor2.
Route vertices are local XY coordinates. Attached network endpoints stay fixed.
"""
from __future__ import annotations

import colorsys
import math
import random
import re
import secrets
from collections import defaultdict
from pathlib import Path
from xml.dom import Node, minidom


ROUTES = {"Conveyor", "Road", "Path", "RailwayTrack"}
CHARTS = {"BarChart", "Plot", "TimePlot", "TimeStackChart", "Histogram", "PieChart", "StackChart"}
MARKUP = {"Wall", "TargetLine", "ServiceWithLine", "PolygonNode", "QueueLine", "ServiceLine",
          "ServicePoint", "DensityMap", "FlowStatistics", "Camera3D", "EscalatorGroup", "Escalator",
          "Elevator", "RectangleNode", "PointNode", "Network", "ConveyorNetwork", "Attractor",
          "PositionOnConveyor", "ConveyorSimpleStation", "Turntable", "PalletRack", "Area"}
ELEMENTS = ROUTES | CHARTS | MARKUP | {"Variable", "EmbeddedObject", "Function", "Event", "HistogramData",
                              "DataSet", "Statistics", "Output", "StatechartElement"}
LANGUAGES = {"ru", "en", "keep"}
OPTIONS = {"seed", "model_name", "rename", "model_language", "elements_language",
           "parameters", "routes", "chart_colors", "vary_geometry", "label_offsets"}
RESERVED = set(("abstract assert boolean break byte case catch char class const continue default do "
                "double else enum extends final finally float for goto if implements import instanceof "
                "int interface long native new package private protected public return short static "
                "strictfp super switch synchronized this throw throws transient try void volatile while "
                "true false null _ var yield record sealed permits").split())


def children(node, tag=None):
    if node is None:
        return []
    return [n for n in node.childNodes if n.nodeType == Node.ELEMENT_NODE and
            (tag is None or n.tagName == tag)]


def child(node, path):
    for tag in path.split("/"):
        node = next(iter(children(node, tag)), None)
    return node


def value(node):
    if node is None:
        return ""
    return "".join(n.data for n in node.childNodes if n.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE))


def field(node, path):
    return value(child(node, path))


def put(node, text):
    if node is None:
        raise ValueError("В шаблоне отсутствует обязательное поле XML")
    doc = node.ownerDocument
    cdata = any(n.nodeType == Node.CDATA_SECTION_NODE for n in node.childNodes)
    for n in list(node.childNodes):
        node.removeChild(n)
    node.appendChild((doc.createCDATASection if cdata else doc.createTextNode)(str(text)))


def load(path):
    raw = Path(path).read_bytes()
    if b"<!DOCTYPE" in raw.upper():
        raise ValueError("Пользовательские XML-сущности в ALP не поддерживаются")
    doc = minidom.parseString(raw)
    model = child(doc.documentElement, "Model")
    if doc.documentElement.tagName != "AnyLogicWorkspace" or model is None:
        raise ValueError("Требуется XML-проект AnyLogic .alp")
    return doc, model


def scopes(model):
    return children(child(model, "ActiveObjectClasses"), "ActiveObjectClass") + children(child(model, "Experiments"))


def elements(owner):
    return [n for n in owner.getElementsByTagName("*") if n.tagName in ELEMENTS and
            child(n, "X") is not None and field(n, "Name")]


def identifier(s):
    if not isinstance(s, str) or not s.isidentifier() or s in RESERVED:
        raise ValueError(f"Недопустимое имя Java: {s!r}")
    return s


def index_model(model):
    return {f"{field(owner, 'Name')}.{field(n, 'Name')}": n
            for owner in scopes(model) for n in elements(owner)}


def resolve(key, index):
    if key in index:
        return key
    hits = [k for k in index if k.split(".", 1)[1] == key]
    if len(hits) != 1:
        raise ValueError(f"Элемент {key!r} отсутствует или неоднозначен. Используйте имя из inspect.")
    return hits[0]


def xyz(p):
    return tuple(float(field(p, axis) or 0) for axis in "XYZ")


def anchors(n):
    pts = children(child(n, "Points"), "Point")
    if len(pts) < 6 or len(pts) % 3:
        return []
    return [list(xyz(p)) for p in pts[::3]]


def inspect_model(source):
    doc, model = load(source)
    index = index_model(model)
    return {"name": field(model, "Name"), "package": field(model, "JavaPackageName"),
            "version": doc.documentElement.getAttribute("AlpVersion"),
            "agents": [field(n, "Name") for n in children(child(model, "ActiveObjectClasses"))],
            "experiments": [{"name": field(n, "Name"), "type": n.tagName,
                             "stop": field(n, "ModelTimeProperties/StopOption")}
                            for n in children(child(model, "Experiments"))],
            "elements": {k: (field(n, "ActiveObjectClass/ClassName") or n.tagName) for k, n in index.items()},
            "parameters": {k: {"type": field(n, "Properties/Type"),
                               "default": field(n, "Properties/DefaultValue/Code")}
                           for k, n in index.items() if n.getAttribute("Class") == "Parameter"},
            "routes": {k: {"type": n.tagName, "anchors": anchors(n),
                           "source": n.getAttribute("SourceId") or None, "target": n.getAttribute("TargetId") or None}
                       for k, n in index.items() if n.tagName in ROUTES},
            "resources": [field(n, "Path") for n in children(child(model, "ModelResources"))]}


def number(x):
    if isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x):
        raise ValueError(f"Ожидалось конечное число, получено {x!r}")
    if isinstance(x, int):
        return str(x)
    return format(x, ".15g")


def set_parameters(index, updates):
    changes = {}
    for k, new in updates.items():
        key = resolve(k, index)
        n = index[key]
        if n.tagName != "Variable" or n.getAttribute("Class") != "Parameter":
            raise ValueError(f"{key}: ожидается параметр агента")
        typ = field(n, "Properties/Type")
        if typ in {"int", "long", "short", "byte"} and type(new) is not int:
            raise ValueError(f"{key}: требуется целое число")
        if typ == "boolean" and type(new) is bool:
            literal = str(new).lower()
        elif typ in {"int","long","short","byte","float","double"}:
            literal = number(new)
            if typ == "long":
                literal += "L"
            if typ == "float":
                literal += "f"
        else:
            raise ValueError(f"{key}: тип {typ!r} или значение не поддерживаются")
        props = child(n, "Properties")
        default = child(props, "DefaultValue")
        if default is None:
            default = n.ownerDocument.createElement("DefaultValue")
            default.setAttribute("Class", "CodeValue")
            props.insertBefore(default, child(props, "ParameterEditor"))
        code = child(default, "Code")
        if code is None:
            code = n.ownerDocument.createElement("Code")
            code.appendChild(n.ownerDocument.createCDATASection(""))
            default.appendChild(code)
        changes[key] = {"before": value(code), "after": literal}
        put(code, literal)
    return changes


def recolor(model, rng):
    mapping = {}
    hue = rng.random()
    for parent in model.getElementsByTagName("*"):
        if parent.tagName not in {"DataItem","HistogramDataExpression","DatasetExpression","DataSetExpression","DataExpression"}:
            continue
        for n in children(parent):
            if not (n.tagName == "Color" or n.tagName.startswith("Color") or n.tagName == "LineColor"):
                continue
            s = value(n)
            if not re.fullmatch(r"-?\d+", s):
                continue
            old = int(s) & 0xffffffff
            rgb = tuple((old >> i) & 255 for i in (16, 8, 0))
            if min(rgb) == max(rgb):
                continue
            if s not in mapping:
                hue = (hue + 0.61803398875) % 1
                r,g,b = (round(c*255) for c in colorsys.hsv_to_rgb(hue, .76, .77))
                new = old & 0xff000000 | r << 16 | g << 8 | b
                if new == old:
                    new ^= 1
                mapping[s] = new - 2**32 if new >= 2**31 else new
            put(n, mapping[s])
    return mapping
def set_points(shape, points):
    container = child(shape, "Points")
    sample = children(container, "Point")[0]
    for p in children(container, "Point"):
        container.removeChild(p)
    for coords in points:
        p = sample.cloneNode(True)
        for axis, coord in zip("XYZ", coords):
            token = child(p, axis)
            if token is not None:
                put(token, number(coord))
        container.appendChild(p)


def vec_add(a, b, factor=1.0):
    return tuple(x + factor*y for x,y in zip(a,b))


def difference(a,b):
    return tuple(x-y for x,y in zip(a,b))


def route_curve(vertices):
    """Anchor, incoming and outgoing handle for each vertex in an ALP cubic path."""
    result = []
    for i, p in enumerate(vertices):
        prev = vertices[max(0, i-1)]
        nxt = vertices[min(len(vertices)-1, i+1)]
        direct = difference(nxt, prev)
        length = math.dist(nxt, prev)
        if length < 1e-6:
            raise ValueError("Соседние вершины образуют разворот на 180 градусов")
        unit = tuple(x/length for x in direct)
        left = math.dist(p,prev) if i else math.dist(nxt,p)
        right = math.dist(nxt,p) if i < len(vertices)-1 else left
        handle = min(left,right)/4
        result.extend([p, vec_add(p, unit, -handle), vec_add(p, unit, handle)])
    return result


def change_routes(index, updates, auto, rng):
    changes = {}
    for label, raw in updates.items():
        key = resolve(label, index)
        n = index[key]
        old = anchors(n)
        if n.tagName not in ROUTES or not old:
            raise ValueError(f"{key}: неизвестный формат геометрии")
        if not isinstance(raw, list) or len(raw) < 2 or len(raw) > 5000:
            raise ValueError(f"{key}: задайте от 2 до 5000 вершин")
        if any(not isinstance(p, (tuple,list)) or len(p) not in (2,3) for p in raw):
            raise ValueError(f"{key}: ожидаются вершины [x,y] или [x,y,z]")
        if any(len(p)==2 for p in raw) and any(abs(p[2])>1e-6 for p in old):
            raise ValueError(f"{key}: укажите высоту каждой вершины наклонного участка")
        vertices = [tuple(float(number(x)) for x in p) + ((0.,) if len(p)==2 else ()) for p in raw]
        if any(math.dist(a,b) < 1e-5 for a,b in zip(vertices, vertices[1:])):
            raise ValueError(f"{key}: совпадающие вершины")
        if math.dist(old[0],vertices[0]) > 1e-4:
            raise ValueError(f"{key}: сохраните первую вершину {old[0]}")
        if (n.tagName in {"Road", "RailwayTrack", "Path"} or n.hasAttribute("TargetId")) and math.dist(old[-1], vertices[-1]) > 1e-4:
            raise ValueError(f"{key}: сохраните конечную точку сети {old[-1]}")
        # Nested stations/sensors are positioned by arc length along the conveyor.
        # Their offset must remain within the edited segment's length.
        chord_length = sum(math.dist(a,b) for a,b in zip(vertices, vertices[1:]))
        for attachment in n.getElementsByTagName("Offset"):
            try:
                offset = float(value(attachment))
            except ValueError:
                continue
            if offset > chord_length:
                raise ValueError(f"{key}: длина участка меньше смещения станции {offset:g}")
        set_points(n, route_curve(vertices))
        changes[key] = {"before": old, "after": vertices}
    if not auto or updates:
        return changes
    # A terminal conveyor may be extended without detaching ports, sensors or other belts.
    for key, n in index.items():
        if n.tagName != "Conveyor" or n.hasAttribute("TargetId"):
            continue
        old = anchors(n)
        if len(old) < 2:
            continue
        points = [xyz(p) for p in children(child(n,"Points"),"Point")]
        # Translate the terminal knot and both handles along its existing tangent.
        direction = difference(points[-3], points[-2])
        norm = math.dist(points[-3], points[-2])
        if norm < 1e-6:
            continue
        distance = math.dist(old[-1],old[-2]) * rng.uniform(.04,.09)
        for i in range(-3,0):
            points[i] = vec_add(points[i],direction,distance/norm)
        set_points(n, points)
        changes[key] = {"before": old, "after": anchors(n), "extension_px": round(distance,3)}
        break
    return changes


def remove_spurs(coords):
    clean = []
    for point in coords:
        while len(clean) >= 2:
            a,b = clean[-2:]
            if a[0] == b[0] == point[0] or a[1] == b[1] == point[1]:
                clean.pop()
            else:
                break
        if not clean or point != clean[-1]:
            clean.append(point)
    return clean


def statechart_spacing(owner, vary, rng):
    shapes = children(child(owner, "StatechartElements"), "StatechartElement")
    states = [s for s in shapes if s.getAttribute("Class") == "State"]
    edges = [s for s in shapes if child(s,"Points") is not None]
    if not states or not edges:
        return None
    intervals = sorted((xyz(s)[0], xyz(s)[0] + float(child(s,"Properties").getAttribute("Width") or 0))
                       for s in states)
    cuts = []
    right = intervals[0][1]
    for start, end in intervals[1:]:
        if start - right >= 30:
            cuts.append((start + right) / 2)
        right = max(right, end)
    if not cuts:
        # A single-state self-loop can have an outer vertical leg. Enlarge the
        # clearance on that side while leaving the attachments to the state fixed.
        left = intervals[0][0]
        far = min((xyz(e)[0]+xyz(p)[0] for e in edges for p in children(child(e,"Points"),"Point")),default=left)
        if left - far >= 30:
            cuts.append((left+far)/2)
    cut = rng.choice(cuts) if cuts and vary else None
    step = rng.choice([10,20]) if cut is not None else 0
    def move(x):
        return x+step if cut is not None and x>=cut else x
    for s in shapes:
        x = xyz(s)[0]
        pts = children(child(s,"Points"),"Point")
        if pts:
            old = [xyz(p)[:2] for p in pts]
            moved = [(move(x+a)-move(x),b) for a,b in old]
            # An icon offset along a transition is set by the designer. Keep all
            # original bends on these curves to preserve its placement.
            if moved != old:
                set_points(s, moved)
        if move(x) != x:
            put(child(s,"X"),number(move(x)))
    return {"spacing_added_px":step, "split_at_x":cut} if step else None


def tidy_layout(model, vary, rng):
    summary = {}
    for owner in scopes(model):
        state_changes = statechart_spacing(owner,vary,rng)
        if state_changes:
            summary[field(owner,"Name")+".statechart"] = state_changes
        wires = children(child(owner, "Connectors"), "Connector")
        blocks = {field(n, "Name"): n for n in children(child(owner, "EmbeddedObjects"), "EmbeddedObject")}
        if not wires or not blocks:
            continue
        # Pick an empty vertical strip between two occupied columns. Translate blocks
        # and all wire vertices to its right by equal amounts to preserve orthogonal runs.
        endpoint_pairs = []
        used = set()
        for wire in wires:
            pts = children(child(wire, "Points"), "Point")
            if not pts:
                continue
            for side, point in [("Source", pts[0]), ("Target", pts[-1])]:
                name = field(wire, side+"EmbeddedObjectReference/ItemName")
                if name in blocks:
                    used.add(name)
                    endpoint_pairs.append((xyz(blocks[name])[0], xyz(wire)[0] + xyz(point)[0]))
        cols = sorted({xyz(blocks[name])[0] for name in used})
        candidates = [(a+b)/2 for a,b in zip(cols,cols[1:]) if b-a >= 80]
        cuts = [c for c in candidates if all((a >= c) == (b >= c) for a,b in endpoint_pairs)]
        cut = rng.choice(cuts) if cuts and vary and len(endpoint_pairs)==2*len(wires) else None
        step = rng.choice([10,20,30]) if cut is not None else 0
        def move_x(x):
            return x + step if cut is not None and x >= cut else x
        if step:
            for name in used:
                n = blocks[name]
                put(child(n,"X"),number(move_x(xyz(n)[0])))
        removed = 0
        for w in wires:
            base = xyz(w)
            old = [xyz(p)[:2] for p in children(child(w,"Points"),"Point")]
            if len(old)<2:
                continue
            new_x = move_x(base[0])
            moved = [(move_x(base[0]+x)-new_x,y) for x,y in old]
            clean = remove_spurs(moved)
            if len(clean)<2:  # A closed wire can be valid.
                clean = moved
            removed += len(old)-len(clean)
            if moved != old or clean != old or new_x != base[0]:
                put(child(w,"X"), number(new_x))
                set_points(w, clean)
        if step or removed:
            summary[field(owner,"Name")] = {"spacing_added_px":step, "split_at_x":cut, "redundant_vertices_removed":removed}
    return summary
# Vocabulary for the course's models. Explicit names always take precedence.
WORDS = dict(row.split("=") for row in """
source=источник sink=выход queue=очередь service=обслуживание select=выбор output=выход
selectOutput=выборВыхода chart=диаграмма plot=график conveyor=конвейер path=путь road=дорога
time=время total=итог measure=замер start=начало end=конец from=от to=до position=позиция
station=станция way=путь tellers=кассиры ATM=банкомат at=у entry=вход exit=выход side=сторона
go=идти train=поезд ped=пешеход wait=ожидание in=вход out=выход tickets=билеты
check=проверка detectors=рамки doors=двери route=маршрут passengers=пассажиры street=улица
mall=тц or=или shop=магазин floor=этаж visit=посетить choice=выбор elevator=лифт
escalator=эскалатор up=вверх down=вниз metro=метро pass=проход throw=через
data=данные dataset=набор current=текущий best=лучший objective=критерий
feasible=допустимый infeasible=недопустимый selected=выбранная view=вид area=область
navigate=перейти rate=интенсивность lottery=лотерея lab=лабораторная ticket=билет
number=количество experiments=экспериментов parameters=параметры variation=варьирование
profit=прибыль cost=себестоимость costs=издержки size=размер demand=спрос
purchase=закупки sum=сумма winnings=выигрыша cars=автомобилей accessories=аксессуаров
equipment=техники waiting=ожидание intensity=интенсивность arrival=прибытия
minimum=мин maximum=макс middle=средний distribution=распределение
statechart=диаграммаСостояний transition=переход delay=задержка statistic=статистика
stat=статистика avg=среднее min=минимум max=максимум S=состояние P=вероятность
k=коэффициент t=время z=случайноеЗначение
line=линия target=цель wall=стена camera=камера level=уровень point=точка
network=сеть pallet=паллеты rack=стеллаж turntable=поворотныйСтол eye=датчик photo=фото
placing=размещение density=плотность map=карта flow=поток statistics=статистика
attractor=место passenger=пассажир customer=клиент places=места group=группа
""".split())
TOKENS = re.compile(r"[A-ZА-ЯЁ]+(?=[A-ZА-ЯЁ][a-zа-яё]|\d|$)|[A-ZА-ЯЁ]?[a-zа-яё]+|[A-ZА-ЯЁ]+|\d+")
RU = re.compile("[А-Яа-яЁё]")
EN = re.compile("[A-Za-z]")
TRANS = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
    "a b v g d e yo zh z i y k l m n o p r s t u f kh ts ch sh sch _ y _ e yu ya".split()))
TYPE_RU = {"Variable":"переменная", "Function":"функция", "Event":"событие", "DataSet":"наборДанных",
           "EmbeddedObject":"блок", "HistogramData":"данныеГистограммы", "Road":"дорога",
           "Conveyor":"конвейер","Path":"путь","RailwayTrack":"рельсы","Output":"показатель",
           "StatechartElement":"состояние","Statistics":"статистика"}


def localize(name, language, fallback):
    if language == "keep" or not (RU if language=="en" else EN).search(name):
        return name
    mapping = WORDS if language=="ru" else {v.casefold():k for k,v in WORDS.items()}
    if language=="ru" and name in WORDS:
        return WORDS[name]
    parts=[]
    for token in TOKENS.findall(name):
        lo = token.casefold()
        converted = mapping.get(token, mapping.get(lo))
        if converted is None and language=="ru" and EN.search(token):
            return fallback
        if converted is None:
            converted = "".join(TRANS.get(c,c) for c in lo) if language=="en" else lo
        if not parts or converted.casefold() != parts[-1].casefold():
            parts.append(converted)
    if not parts:
        return fallback
    return parts[0] + "".join(p[:1].upper()+p[1:] for p in parts[1:])


# Tokenize only Java identifiers, keeping comments and quoted literals byte-for-byte.
JAVA = re.compile(r'(""".*?"""|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|//[^\n]*|/\*.*?\*/)|([\w$]+)', re.S)
QUALIFIER = re.compile(r'([\w$]+)\s*\.\s*$')


def rewrite_code(text, local, receivers, model_types):
    declared = dict(receivers)
    for typename, name in re.findall(r"\b([\w$]+)\s+([\w$]+)\s*(?=[=;,)])", text):
        if typename in model_types:
            declared[name] = model_types[typename]
    def replace(match):
        token = match.group(2)
        if token is None:
            return match.group()
        owner = QUALIFIER.search(text[:match.start()]) if "." in text[max(0,match.start()-40):match.start()] else None
        if owner:
            name = owner.group(1)
            replacements = declared.get(name, {})
        else:
            replacements = local
        return replacements.get(token,token)
    return JAVA.sub(replace,text)


def apply_names(model, index, rename, language):
    manual={resolve(k,index):identifier(v) for k,v in rename.items()}
    by_scope = {}
    changes = {}
    for owner in scopes(model):
        scope=field(owner,"Name")
        locals_={}
        occupied={field(x,"Name") for x in owner.getElementsByTagName("*") if
                  child(x,"Id") is not None and child(x,"X") is not None}
        for n in elements(owner):
            old=field(n,"Name")
            key=scope+"."+old
            fallback = TYPE_RU.get(n.tagName, "график" if n.tagName in CHARTS else "элемент")
            new=manual[key] if key in manual else localize(old,language,fallback)
            if new==old:
                continue
            if key in manual and new in occupied:
                raise ValueError(f"{key}: имя {new} уже используется")
            base=new
            i=2
            while new in occupied or new in RESERVED:
                new=f"{base}{i}"
                i+=1
            identifier(new)
            locals_[old]=new
            occupied.add(new)
            changes[key]=new
            put(child(n,"Name"),new)
        by_scope[scope]=locals_
    if not changes:
        return {}
    agents = {field(n,"Id"): field(n,"Name") for n in children(child(model,"ActiveObjectClasses"))}
    model_types = {name:by_scope[name] for name in agents.values()}
    # The flow libraries expose the moving entity as agent/ped in block actions.
    # In the course examples these fields belong to a single entity class. Where
    # there are multiple classes, infer only field translations shared by them.
    possibilities = defaultdict(set)
    for name in agents.values():
        if name != "Main":
            for key, member in index.items():
                owner, old = key.split(".",1)
                if owner == name:
                    possibilities[old].add(by_scope[name].get(old,old))
    entity = {old:next(iter(names)) for old,names in possibilities.items() if len(names)==1}
    package=field(model,"JavaPackageName")
    for n in model.getElementsByTagName("ItemName"):
        ref = n.parentNode
        if field(ref,"PackageName")==package:
            replacement=by_scope.get(field(ref,"ClassName"),{}).get(value(n))
            if replacement:
                put(n,replacement)
    for owner in scopes(model):
        local=by_scope[field(owner,"Name")]
        top=by_scope.get(agents.get(owner.getAttribute("ActiveObjectClassId"),"Main"),{})
        receivers={"root":top, "main":top, "this":local, "agent":entity, "ped":entity}
        for key, block in index.items():
            if key.split(".",1)[0] == field(owner,"Name") and block.tagName == "EmbeddedObject":
                model_type = field(block,"ActiveObjectClass/ClassName")
                if model_type in model_types:
                    receivers[key.split(".",1)[1]] = model_types[model_type]
        # Parameter names are also available unqualified in an experiment editor.
        combined=dict(local)
        if owner.tagName!="ActiveObjectClass":
            top_name=agents.get(owner.getAttribute("ActiveObjectClassId"),"Main")
            top_parameters={k.split(".",1)[1] for k,v in index.items() if
                            k.startswith(top_name+".") and v.getAttribute("Class")=="Parameter"}
            combined={**{k:v for k,v in top.items() if k in top_parameters},**local}
        for n in owner.getElementsByTagName("*"):
            tag=n.tagName
            if tag=="ParameterName" and value(n) in top:
                put(n,top[value(n)])
            elif (tag=="Name" and n.parentNode.tagName=="Parameter" and
                  n.parentNode.parentNode.parentNode.tagName=="EmbeddedObject"):
                ref=child(n.parentNode.parentNode.parentNode,"ActiveObjectClass")
                if field(ref,"PackageName")==package:
                    replacement=by_scope.get(field(ref,"ClassName"),{}).get(value(n))
                    if replacement:
                        put(n,replacement)
            elif tag in {"Code","Body","Value","Camera","Condition","Expression2","Equation","Derivative","Guard"} or tag.endswith(("Code","Expression","Action")):
                if not children(n):
                    before=value(n)
                    after=rewrite_code(before,combined,receivers,model_types)
                    if after!=before:
                        put(n,after)
    return changes


def arrange_labels(model, index, offsets):
    """Place colliding block labels on separate rows; preserve manual positions."""
    overrides = {resolve(k, index): xy for k, xy in offsets.items()}
    result = {}
    for owner in scopes(model):
        placed = []
        for block in children(child(owner, "EmbeddedObjects"), "EmbeddedObject"):
            label = child(block, "Label")
            if label is None or field(block, "ShowLabel") == "false":
                continue
            key = field(owner, "Name") + "." + field(block, "Name")
            x, y = xyz(block)[:2]
            dx, dy = xyz(label)[:2]
            old = [dx, dy]
            manual = key in overrides
            if manual:
                pair = overrides.pop(key)
                if not isinstance(pair, list) or len(pair) != 2:
                    raise ValueError(f"{key}: нужны смещения [x,y]")
                dx, dy = [float(number(v)) for v in pair]
            width = 7 * len(field(block, "Name")) + 5
            while not manual and any(x+dx < r and x+dx+width > l and
                    abs(y+dy-ty) < 15 for l, r, ty in placed):
                dy -= 17
            placed.append((x+dx, x+dx+width, y+dy))
            if old != [dx, dy]:
                put(child(label, "X"), number(dx))
                put(child(label, "Y"), number(dy))
                result[key] = [dx, dy]
    if overrides:
        raise ValueError(f"Не найдены видимые подписи блоков: {list(overrides)}")
    return result


def generate(source, destination, spec=None):
    spec={} if spec is None else spec
    if not isinstance(spec,dict) or set(spec)-OPTIONS:
        raise ValueError(f"Разрешённые поля спецификации: {sorted(OPTIONS)}")
    for k in ("model_language","elements_language"):
        if spec.get(k,"keep") not in LANGUAGES:
            raise ValueError(f"{k}: укажите ru, en или keep")
    for k in ("rename","parameters","routes","label_offsets"):
        if not isinstance(spec.get(k,{}),dict):
            raise ValueError(f"{k}: требуется объект JSON")
    for k in ("chart_colors","vary_geometry"):
        if type(spec.get(k,True)) is not bool:
            raise ValueError(f"{k}: укажите true или false")
    seed=spec.get("seed",secrets.randbelow(2**31-1)+1)
    if type(seed) is not int or not 0<=seed<=2**31-1:
        raise ValueError("seed должен быть целым от 0 до 2147483647")
    rng=random.Random(seed)
    doc,model=load(source)
    index=index_model(model)
    old_name=field(model,"Name")
    language=spec.get("model_language","keep")
    name=spec.get("model_name",localize(old_name,language,"Модель"))
    if not isinstance(name,str) or not name.strip() or any(ord(c)<32 for c in name):
        raise ValueError("Ожидается непустое имя модели")
    if language=="en" and RU.search(name) or language=="ru" and EN.search(name):
        raise ValueError("model_name не соответствует model_language")
    put(child(model,"Name"),name)
    for exp in children(child(model,"Experiments")):
        title=child(exp,"PresentationProperties/Title")
        if title and value(title).startswith(old_name+" : "):
            put(title,name + value(title)[len(old_name):])
        for t in exp.getElementsByTagName("Text"):
            if not children(t) and value(t)==old_name:
                put(t,name)
    changed_seeds=[]
    for exp in children(child(model,"Experiments")):
        if field(exp,"RandomNumberGenerationType")=="fixedSeed" and child(exp,"SeedValue") is not None:
            put(child(exp,"SeedValue"),seed)
            changed_seeds.append(field(exp,"Name"))
    change={"seed":seed, "seeded_experiments":changed_seeds,"name":name,
            "parameters":set_parameters(index,spec.get("parameters",{})),
            "routes":change_routes(index,spec.get("routes",{}),spec.get("vary_geometry",True),rng),
            "layout":tidy_layout(model,spec.get("vary_geometry",True),rng),
            "colors":recolor(model,rng) if spec.get("chart_colors",True) else {},
            "renamed":apply_names(model,index,spec.get("rename",{}),spec.get("elements_language","keep"))}
    change["labels"] = arrange_labels(model, index_model(model), spec.get("label_offsets", {}))
    # Exclusive creation permits safe parallel generation and preserves input projects.
    dest=Path(destination)
    data=doc.toxml(encoding="UTF-8")
    minidom.parseString(data).unlink()
    dest.parent.mkdir(parents=True,exist_ok=True)
    with dest.open("xb") as stream:
        stream.write(data)
    return change
