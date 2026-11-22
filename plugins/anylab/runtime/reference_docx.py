"""Fill an original DOCX by position, keeping its Word layout objects."""
import hashlib
from pathlib import Path

from docx import Document


def load_template(path):
    source = Path(path).resolve(strict=True)
    if source.suffix.lower() != ".docx":
        raise ValueError("Для сохранения исходной структуры нужен DOCX")
    data = source.read_bytes()
    return source, hashlib.sha256(data).hexdigest(), Document(source)


def fields(doc):
    # The order is stable for identical input bytes, including paragraphs within tables.
    text = {str(i): p for i, p in enumerate(doc.element.body.xpath(".//w:p"), 1)
            if any((n.text or "").strip() for n in p.xpath(".//w:t"))}
    images = {str(i): image for i,image in enumerate(doc.element.body.xpath(".//a:blip[@r:embed]"),1)}
    return text, images


def inspect_reference(template):
    source, digest, doc = load_template(template)
    text, images = fields(doc)
    paragraphs = [{"id": key, "text": "".join(t.text or "" for t in p.xpath(".//w:t")),
                   "runs": [t.text or "" for t in p.xpath(".//w:t")],
                   "in_table": bool(p.xpath("ancestor::w:tc")),
                   "style": next(iter(p.xpath("./w:pPr/w:pStyle/@w:val")), "Normal")}
                  for key,p in text.items()]
    figures=[]
    for key, image in images.items():
        drawing=next(iter(image.xpath("ancestor::w:drawing[1]")),None)
        layout=drawing.xpath(".//wp:extent") if drawing is not None else []
        name=drawing.xpath(".//wp:docPr/@name") if drawing is not None else []
        figures.append({"id":key,"name":name[0] if name else "",
                        "size_emu":dict(layout[0].attrib) if layout else {}})
    return {"template":str(source),"sha256":digest,"paragraphs":paragraphs,"images":figures}


def checked_mapping(nodes, updates, keep, kind):
    if not isinstance(updates,dict) or not isinstance(keep,list):
        raise ValueError(f"{kind}: укажите словарь замен и список сохраняемых идентификаторов")
    changed = set(updates)
    kept = set(keep)
    if changed & kept or (changed | kept) - nodes.keys():
        raise ValueError(f"{kind}: неверные или пересекающиеся идентификаторы")
    missing = nodes.keys() - changed - kept
    if missing:
        raise ValueError(f"{kind}: без решения остались поля {', '.join(sorted(missing,key=int)[:16])}")


def refill_reference(template, destination, values):
    from docx.oxml.ns import qn
    source, digest, doc = load_template(template)
    if values.get("sha256") != digest:
        raise ValueError("Шаблон изменился. Повторите разметку его полей.")
    text, images = fields(doc)
    replacements, assets = values.get("paragraphs",{}), values.get("images",{})
    checked_mapping(text,replacements,values.get("keep_paragraphs",[]),"Текст")
    checked_mapping(images,assets,values.get("keep_images",[]),"Снимки")
    for key,new in replacements.items():
        nodes = text[key].xpath(".//w:t")
        if isinstance(new,str):
            # Preserve the first original run properties. Use a list for mixed text styling.
            new = [new] + [""] * (len(nodes)-1)
        if not isinstance(new,list) or len(new)!=len(nodes) or any(
                not isinstance(item,str) or "\n" in item or "\r" in item for item in new):
            raise ValueError(f"Абзац {key}: заполните {len(nodes)} текстовых полей или передайте строку")
        for node,val in zip(nodes,new):
            node.text = val
            if val != val.strip():
                node.set(qn("xml:space"),"preserve")
    for key,path in assets.items():
        rel,image = doc.part.get_or_add_image(str(Path(path).resolve(strict=True)))
        images[key].set(qn("r:embed"),rel)
        drawing = images[key].xpath("ancestor::w:drawing[1]")
        if drawing:
            # Fit within the reference's box without changing the image's aspect ratio.
            extent = drawing[0].xpath(".//wp:extent")[0]
            width, height = int(extent.get("cx")), int(extent.get("cy"))
            ratio = image.px_width / image.px_height
            fitted_width = min(width, round(height * ratio))
            fitted_height = round(fitted_width / ratio)
            extent.set("cx",str(fitted_width))
            extent.set("cy",str(fitted_height))
            for shape_extent in drawing[0].xpath(".//a:xfrm/a:ext"):
                shape_extent.set("cx",str(fitted_width))
                shape_extent.set("cy",str(fitted_height))
    # Keep cover/section/header relationships. Drop old embedded screenshots from body.
    references = {v for n in doc.element.iter() for k,v in n.attrib.items()
                  if k.startswith("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}")}
    for rel in list(doc.part.rels.values()):
        if rel.reltype.rsplit("/",1)[-1]=="image" and rel.rId not in references:
            del doc.part.rels[rel.rId]
    dest = Path(destination).resolve()
    if dest.suffix.lower() != ".docx":
        raise ValueError("Нужен выходной DOCX")
    dest.parent.mkdir(parents=True,exist_ok=True)
    with dest.open("xb") as stream:
        doc.save(stream)
    return {"report":str(dest),"template":str(source),"template_sha256":digest,
            "updated_paragraphs":len(replacements),"updated_images":len(assets)}
