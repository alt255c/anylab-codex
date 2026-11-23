"""Build report figures from verified native window captures without redrawing them."""
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageChops


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def native_crop(item):
    path = Path(item["path"]).resolve(strict=True)
    sidecar = path.with_name(path.name + ".capture.json")
    if not sidecar.is_file():
        raise ValueError("Нужен исходный кадр инструмента capture с файлом .capture.json")
    proof = json.loads(sidecar.read_text(encoding="utf8"))
    if proof.get("kind") != "anylogic-window-capture" or proof.get("sha256") != digest(path):
        raise ValueError("Исходный снимок изменён после capture")
    with Image.open(path) as original:
        image = original.convert("RGB")
    box = item.get("box", [0, 0, image.width, image.height])
    if (not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box)
            or not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height)):
        raise ValueError("box: четыре целых координаты внутри исходного снимка")
    return image.crop(tuple(box)), {"path": str(path), "box": box, "sha256": proof["sha256"]}


def compose(sources):
    if not isinstance(sources, list) or not 1 <= len(sources) <= 8:
        raise ValueError("Укажите от одного до восьми исходных кадров capture")
    panels, recipes = zip(*(native_crop(item) for item in sources))
    width = max(p.width for p in panels)
    height = sum(p.height for p in panels) + 24 * (len(panels) - 1)
    if width * height > 32_000_000:
        raise ValueError("Слишком большой составной снимок")
    figure = Image.new("RGB", (width, height), "white")
    y = 0
    for panel in panels:
        figure.paste(panel, ((width - panel.width) // 2, y))
        y += panel.height + 24
    return figure, list(recipes)


def capture_figure(sources, destination):
    """Crop or stack actual captures; no scaling, painted blocks or arrows."""
    target = Path(destination).resolve()
    if target.suffix.lower() != ".png" or target.exists():
        raise ValueError("Укажите новый PNG для иллюстрации")
    figure, recipe = compose(sources)
    target.parent.mkdir(parents=True, exist_ok=True)
    figure.save(target)
    proof = {"kind": "anylogic-capture-figure", "sha256": digest(target), "sources": recipe}
    target.with_name(target.name + ".figure.json").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2), encoding="utf8")
    return {"file": str(target), "dimensions": figure.size, "sources": recipe}


def validate_capture_figure(path):
    """Reject drawn diagrams or alterations of the screenshot panels."""
    target = Path(path).resolve(strict=True)
    sidecar = target.with_name(target.name + ".figure.json")
    if not sidecar.is_file():
        # A whole native screenshot is also an acceptable figure.
        native_crop({"path": str(target)})
        return
    proof = json.loads(sidecar.read_text(encoding="utf8"))
    if proof.get("kind") != "anylogic-capture-figure" or proof.get("sha256") != digest(target):
        raise ValueError("Иллюстрация изменена после capture_figure")
    expected, recipes = compose(proof["sources"])
    if recipes != proof["sources"]:
        raise ValueError("Источники иллюстрации изменены")
    with Image.open(target) as image:
        actual = image.convert("RGB")
    if actual.size != expected.size or ImageChops.difference(actual, expected).getbbox():
        raise ValueError("Иллюстрация должна содержать только фрагменты исходных снимков")
