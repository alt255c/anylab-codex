"""Fill local templates while retaining the supplied Word layout and AnyLogic objects."""
import re
from pathlib import Path
from xml.dom import minidom

TOKEN = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
IMAGE = re.compile(r"\{\{image:([A-Z0-9_]+)\}\}")
ROWS = re.compile(r"\{\{rows:([A-Z0-9_]+)\}\}")


def fill_report(template, destination, values):
    from docx import Document
    from docx.shared import Cm
    src, dest = Path(template).resolve(strict=True), Path(destination).resolve()
    if src.suffix.lower() != ".docx" or dest.suffix.lower() != ".docx":
        raise ValueError("Требуется шаблон DOCX и новый файл DOCX")
    doc = Document(src)
    text = values.get("text", {})
    images = values.get("images", {})
    tables = values.get("tables", {})
    missing = set()

    def replace(match, mapping):
        key = match[1]
        val = mapping.get(key)
        if val is None or (isinstance(val, str) and not val.strip()):
            missing.add(key)
            return match[0]
        return str(val)

    for p in doc.paragraphs:
        image = IMAGE.fullmatch(p.text.strip())
        if image:
            filename = replace(image, images)
            if IMAGE.fullmatch(filename):
                continue
            p.clear()
            p.add_run().add_picture(filename, width=Cm(14))
            p.paragraph_format.keep_with_next = True
            continue
        for run in p.runs:
            changed = TOKEN.sub(lambda hit: replace(hit, text), run.text)
            if changed != run.text:
                run.text = changed
    for table in doc.tables:
        for row in list(table.rows):
            marker = ROWS.fullmatch(row.cells[0].text.strip())
            if marker:
                data = tables.get(marker[1])
                if not data:
                    missing.add(marker[1])
                    continue
                count = len(row.cells)
                if any(len(r)!=count for r in data):
                    raise ValueError(f"Таблица {marker[1]} должна содержать {count} столбцов")
                for fields in data:
                    for cell, val in zip(table.add_row().cells, fields):
                        cell.text = str(val)
                table._tbl.remove(row._tr)
            else:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        for run in p.runs:
                            changed = TOKEN.sub(lambda hit: replace(hit,text),run.text)
                            if changed != run.text:
                                run.text = changed
    if missing:
        raise ValueError("Заполните поля: " + ", ".join(sorted(missing)))
    dest.parent.mkdir(parents=True,exist_ok=True)
    with dest.open("xb") as f:
        doc.save(f)
    return {"report":str(dest),"template":str(src)}


def patch_model(path, block_code):
    from models import children, child, field, put
    if not block_code:
        return
    doc = minidom.parse(str(path))
    agents = children(child(doc.documentElement,"Model/ActiveObjectClasses"),"ActiveObjectClass")
    index = {}
    for agent in agents:
        for block in children(child(agent,"EmbeddedObjects"),"EmbeddedObject"):
            for slot in children(child(block,"Parameters"),"Parameter"):
                key = ".".join(field(n,"Name") for n in (agent,block,slot))
                node = child(slot,"Value/Code")
                if node is not None:
                    index[key] = node
    for key,value in block_code.items():
        if key not in index or not isinstance(value,str) or not value.strip() or "]]>" in value:
            raise ValueError(f"Неверное поле блока: {key}")
        put(index[key],value)
    path.write_bytes(doc.toxml(encoding="UTF-8"))
