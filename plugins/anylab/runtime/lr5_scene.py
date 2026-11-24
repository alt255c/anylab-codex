"""Optional, reproducible scene changes for the canonical Lab 5 models."""
import math
import re

from bridge.anylogic import field, put
from models import anchors, child, children, route_curve, set_points, xyz

THEMES = {
    "classic": ("#19B6B0", "#F28A3C", "#2457CC", "#F28A3C", "#FFF1CF", None),
    "retro_factory": ("#C59444", "#842E42", "#203A65", "#49382A", "#D9B785", "#9A743D"),
    "smart_factory": ("#21AAA6", "#ED8A44", "#275ACA", "#253F48", "#BCD9D5", "#4F6068"),
    "sci_fi": ("#56C4D7", "#DE804C", "#6B71F0", "#432F65", "#D2CCEA", "#454467"),
}
COLOR_KEYS = ("ordinary", "fragile", "manual", "tape", "sheet", "rollers")


def argb(color):
    return str(int("ff" + color[1:], 16) - 2**32)


def scene_options(scene=None):
    if scene is None:
        return {}
    if not isinstance(scene, dict) or set(scene) - {
        "theme", "colors", "label", "label_color", "label_angle",
        "part_color", "wall", "inlet", "sign",
    }:
        raise ValueError("Укажите допустимые настройки scene из README")
    config = dict(scene)
    theme = config.get("theme")
    if "theme" in config and (not isinstance(theme, str) or theme not in THEMES):
        raise ValueError("Темы: classic, retro_factory, smart_factory, sci_fi")
    colors = config.get("colors", {})
    if not isinstance(colors, dict) or set(colors) - set(COLOR_KEYS):
        raise ValueError("Цвета: ordinary, fragile, manual, tape, sheet, rollers")
    for color in [*colors.values(), config.get("label_color", "#B92129"), config.get("part_color", "#AD5744")]:
        if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            raise ValueError("Укажите цвета в формате #RRGGBB")
    label = config.get("label", "")
    if not isinstance(label, str) or not re.fullmatch(r"[A-Za-z0-9 .&-]{0,12}", label):
        raise ValueError("Наклейка: до 12 латинских букв, цифр или знаков .&-")
    angle = config.get("label_angle", 41)
    if type(angle) not in (int, float) or not math.isfinite(angle) or not -180 <= angle <= 180:
        raise ValueError("Угол наклейки: от −180 до 180 градусов")
    if config.get("wall", "outside" if theme == "retro_factory" else "none") not in {"none", "outside"}:
        raise ValueError("Стена: none или outside")
    if config.get("inlet", "straight") not in {"straight", "transfer_table"}:
        raise ValueError("Вход: straight или transfer_table")
    sign = config.get("sign", "")
    if not isinstance(sign, str) or len(sign) > 50 or any(ord(c) < 32 for c in sign):
        raise ValueError("Вывеска: до 50 символов одной строкой")
    return config


def tracks(main):
    return {field(node, "Name"): node for node in main.getElementsByTagName("Conveyor")}


def merge_inlet(doc, main):
    """Replace the optional transfer table with a single continuous conveyor."""
    belts = tracks(main)
    if "loadingBelt" not in belts:
        return
    inlet, belt = belts["loadingBelt"], belts["conveyor"]
    table = next((n for n in main.getElementsByTagName("Turntable") if field(n, "Name") == "loadingTransfer"), None)
    if table is None or inlet.getAttribute("TargetId") != field(table, "Id") or belt.getAttribute("SourceId") != field(table, "Id"):
        raise ValueError("Не найдена штатная связь загрузочной ленты с основным участком")
    extension = float(field(belt, "X")) - float(field(inlet, "X"))
    if extension <= 0 or not math.isclose(float(field(belt, "Y")), float(field(inlet, "Y")), abs_tol=1e-6):
        raise ValueError("Для прямого входа ленты должны быть на одной оси")
    points = [(x + extension, y, z) for x, y, z in map(xyz, children(child(belt, "Points"), "Point"))]
    points[1] = (extension * 2 / 3, 0, 0)
    set_points(belt, [(0, 0, 0), (-extension / 3, 0, 0), (extension / 3, 0, 0), *points])
    put(belt, "X", field(inlet, "X"))
    belt.removeAttribute("SourceId")
    presentation = child(belt, "Presentation")
    for position in children(presentation, "PositionOnConveyor"):
        put(position, "Offset", str(float(field(position, "Offset")) + extension))
    for position in children(child(inlet, "Presentation"), "PositionOnConveyor"):
        presentation.appendChild(position)
    inlet.parentNode.removeChild(inlet)
    table.parentNode.removeChild(table)
    for code in doc.getElementsByTagName("Code"):
        if field(code.parentNode, "Code").strip() == "loadingBelt":
            code.firstChild.data = "conveyor"


def add_s_curve(main):
    """Move the belt after the assembly station while retaining both network endpoints."""
    belt = tracks(main)["conveyor"]
    old = anchors(belt)
    if len(old) != 2 or old[1][0] <= 480:
        raise ValueError("S-изгиб требует штатного прямого участка ЛР5")
    points = route_curve([(0, 0, 0), (277, 0, 0), (322, 13, 0), (365, 48, 0),
                          (405, 48, 0), (447, 13, 0), (479, 0, 0), tuple(old[-1])])
    set_points(belt, points)
    previous = points[0]
    distance = 0.0
    sensor = next(p for p in belt.getElementsByTagName("PositionOnConveyor") if field(p, "Name") == "photoEye")
    target_x = float(field(sensor, "Offset"))
    for i in range(0, len(points) - 3, 3):
        a, b, c, d = points[i], points[i + 2], points[i + 4], points[i + 3]
        for step in range(1, 101):
            t = step / 100
            q = tuple((1-t)**3*a[j] + 3*(1-t)**2*t*b[j] + 3*(1-t)*t*t*c[j] + t**3*d[j] for j in range(3))
            segment = math.dist(previous, q)
            if q[0] >= target_x:
                ratio = (target_x - previous[0]) / (q[0] - previous[0])
                put(sensor, "Offset", str(round(distance + ratio * segment, 3)))
                return
            distance += segment
            previous = q
    raise ValueError("Не удалось сохранить датчик на S-изгибе")


class Shapes:
    def __init__(self, doc):
        self.ident = max(int(n.firstChild.data) for n in doc.getElementsByTagName("Id")
                         if n.firstChild and n.firstChild.data.isdecimal())

    def clone(self, prototype, name, **properties):
        node = prototype.cloneNode(True)
        self.ident += 1
        for key, value in {"Id": self.ident, "Name": name, **properties}.items():
            put(node, key, str(value))
        return node


def add_wall(main, shapes, full):
    """Build a backdrop outside the canonical interior, with a visible aisle."""
    presentation = child(main, "Presentation")
    floor = next(n for n in presentation.getElementsByTagName("Rectangle") if field(n, "Name") == "rectangle3")

    def block(name, x, y, z, width, depth, height, color):
        shape = shapes.clone(floor, name, X=x, Y=y, Z=z, Width=width, Height=depth, ZHeight=height,
                             FillColor=argb(color), DrawMode="SHAPE_DRAW_3D", PublicFlag="false")
        presentation.insertBefore(shape, presentation.firstChild)

    # The working scene begins at Y >= 0. The masonry ends at Y = -86.
    left, count = (-315, 8) if full else (-86, 5)
    block("sceneApron", left - 14, -118, -1, 196 * (count - 1) + 172, 114, 1, "#C1AD93")
    for bay in range(count):
        x = left + 196 * bay
        block(f"sceneMortar{bay}", x, -102, 3, 144, 8, 41, "#74554A")
        for row in range(4):
            for column, offset in enumerate(range(-14 if row % 2 else 0, 144, 29)):
                lo, hi = max(0, offset + 1), min(144, offset + 28)
                if hi > lo:
                    shade = ("#A75843", "#9A4C3C", "#88483C")[(row + column + bay) % 3]
                    block(f"sceneMasonry{bay}_{row}_{column}", x + lo, -94, 4 + row * 10, hi - lo, 2, 8, shade)
        for end, dx in enumerate((-3, 137)):
            block(f"scenePost{bay}_{end}", x + dx, -105, 0, 10, 16, 47, "#8F663E")
        block(f"sceneCap{bay}", x - 2, -103, 44, 148, 13, 4, "#AC8953")


def add_sign(main, shapes, title):
    presentation = child(main, "Presentation")
    prototype = next(n for n in presentation.getElementsByTagName("Text") if child(n, "Font") and child(n, "Name"))
    node = shapes.clone(prototype, "sceneSign", X=-95, Y=26, Text=title, Color=argb("#65492E"),
                        Rotation=0, DrawMode="SHAPE_DRAW_2D")
    put(child(node, "Font"), "Size", "13")
    presentation.insertBefore(node, presentation.firstChild)


def brick(carton, shapes, config):
    from PIL import Image, ImageDraw, ImageFont

    presentation = child(carton, "Presentation/Level/Presentation")
    elements = {field(n, "Name"): n for n in children(presentation)}
    sheet = elements["sheet"]
    reference = elements["glassRim"]
    visible = field(elements["component3D"], "VisibleCode")
    base = "(cargoRole==1 ? 0 : (isManuallyAdded ? 2 : 8))"
    degrees = config.get("label_angle", 41)
    angle = math.radians(degrees)

    def rect(name, x, y, w, h, z, depth, color, mode, z_code=None):
        node = shapes.clone(sheet, name, X=x * math.cos(angle) - y * math.sin(angle),
                            Y=x * math.sin(angle) + y * math.cos(angle), Width=w, Height=h,
                            Z=z, ZHeight=depth, LineWidth=0, FillColor=argb(color), LineColor=argb(color),
                            Rotation=degrees, DrawMode=mode, VisibleCode=visible)
        if z_code is not None:
            put(node, "ZCode", z_code)
        return node

    for key, z, depth, mode in (("component3D", 0, 6, "SHAPE_DRAW_3D"), ("component2D", 28, 0, "SHAPE_DRAW_2D")):
        node = rect(key, -10, -5.5, 20, 11, z, depth, config.get("part_color", "#AD5744"),
                    mode, base if depth else None)
        presentation.replaceChild(node, elements[key])
    for key in ("bore2D", "bore3D"):
        presentation.removeChild(elements[key])
    label = config.get("label", "").strip()
    if label:
        font = ImageFont.load_default()
        x0, y0, x1, y1 = font.getbbox(label)
        image = Image.new("1", (x1 - x0, y1 - y0))
        ImageDraw.Draw(image).text((-x0, -y0), label, fill=1, font=font)
        scale = min(15.8 / image.width, 4.0 / image.height)
        presentation.insertBefore(rect("brickSticker", -8.7, -2.5, 17.4, 5, 6.05, .07, "#F5DE9A",
                                       "SHAPE_DRAW_2D3D", base + "+6.05"), reference)
        for y in range(image.height):
            row = "".join(str(int(bool(image.getpixel((x, y))))) for x in range(image.width))
            for run in re.finditer("1+", row):
                node = rect(f"brickInk{y}_{run.start()}", (run.start() - image.width/2) * scale,
                            (y - image.height/2) * scale, len(run.group()) * scale, scale, 6.13, .04,
                            config.get("label_color", "#B92129"), "SHAPE_DRAW_2D3D", base + "+6.13")
                presentation.insertBefore(node, reference)
    refresh = next(n for n in children(child(carton, "Functions"), "Function") if field(n, "Name") == "refreshCargo")
    put(refresh, "Body", "\n".join(
        f'{field(n, "Name")}.setVisible({field(n, "VisibleCode")});\n{field(n, "Name")}.updateDynamicProperties();'
        for n in children(presentation)))


def apply_scene(doc, main, carton, config, component, layout, full):
    colors = dict(zip(COLOR_KEYS, THEMES[config["theme"]])) if "theme" in config else {}
    colors.update(config.get("colors", {}))
    for shape in children(child(carton, "Presentation/Level/Presentation")):
        label = field(shape, "Name")
        key = None
        if any(word in label.lower() for word in ("box", "flap", "closedlid", "carton2d")):
            key = "fragile" if label.startswith("fragile_") else "manual" if label.startswith("manual_") else "ordinary"
        elif label in {"tape2D", "tape3D"}:
            key = "tape"
        elif label == "sheet" or label.startswith("blank"):
            key = "sheet"
        if colors.get(key):
            for prop in ("FillColor", "LineColor"):
                put(shape, prop, argb(colors[key]))
    if colors.get("rollers"):
        for belt in tracks(main).values():
            put(belt, "LineColor", argb(colors["rollers"]))
    if layout == "smooth_s":
        add_s_curve(main)
    if full and config.get("inlet", "straight") == "straight":
        merge_inlet(doc, main)
    shapes = Shapes(doc)
    if config.get("wall", "outside" if config.get("theme") == "retro_factory" else "none") == "outside":
        add_wall(main, shapes, full)
    if config.get("sign"):
        add_sign(main, shapes, config["sign"])
    if component == "brick":
        brick(carton, shapes, config)
