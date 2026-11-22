"""Local course library and report preparation. Source text is indexed as data."""

from contextlib import closing
from datetime import date
from io import BytesIO
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile


DOCUMENTS = {".pdf", ".docx", ".pptx", ".txt", ".md"}
SUPPORTED = DOCUMENTS | {".alp", ".zip", ".rar", ".mp4"}
ROLES = {"report", "lecture", "assignment", "reference"}
NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
      "a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


def _fold(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().replace("ё", "е").split())


def _db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS sources (
            source TEXT PRIMARY KEY, container TEXT, role TEXT, size INTEGER, status TEXT);
        CREATE TABLE IF NOT EXISTS passages (
            source TEXT REFERENCES sources(source) ON DELETE CASCADE,
            locator TEXT, text TEXT, folded TEXT);
        CREATE INDEX IF NOT EXISTS passage_source ON passages(source);
    """)
    return con


def _role(name, override):
    if override is not None:
        if override not in ROLES:
            raise ValueError(f"Неизвестная роль материала: {override}")
        return override
    s = Path(name).suffix.lower()
    if s == ".alp":
        return "model"
    if s == ".mp4":
        return "video"
    if s in {".zip", ".rar"}:
        return "archive"
    stem = Path(name).stem.lower()
    # «по_лекции_СМВС_ЛР3_Игнатов» is an authored report.
    if re.search(r"игнатов|солдаткин|отч[её]т|по[ _-]лекции", stem) or stem.startswith("смвс2"):
        return "report"
    if re.search(r"лекци|lecture", stem):
        return "lecture"
    if re.search(r"задани|assignment", stem):
        return "assignment"
    return "reference"


def _passages(stream, suffix):
    if suffix == ".pdf":
        from pypdf import PdfReader
        for i, page in enumerate(PdfReader(stream).pages, 1):
            yield f"стр. {i}", page.extract_text() or ""
    elif suffix in {".docx", ".pptx"}:
        with ZipFile(stream) as z:
            if suffix == ".docx":
                part = ET.fromstring(z.read("word/document.xml"))
                for i, p in enumerate(part.iterfind(".//w:p", NS), 1):
                    yield f"абз. {i}", "".join(t.text or "" for t in p.iterfind(".//w:t", NS))
            else:
                for path in z.namelist():
                    slide = re.fullmatch(r"ppt/slides/slide(\d+)\.xml", path)
                    if slide:
                        part = ET.fromstring(z.read(path))
                        lines = ["".join(t.text or "" for t in p.iterfind(".//a:t", NS))
                                 for p in part.iterfind(".//a:p", NS)]
                        yield f"слайд {slide[1]}", "\n".join(lines)
    elif suffix in {".txt", ".md"}:
        raw = stream.read()
        try:
            body = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            body = raw.decode("cp1251")
        for i, p in enumerate(re.split(r"\n\s*\n", body), 1):
            yield f"абз. {i}", p
    elif suffix == ".alp":
        model = ET.parse(stream).find("Model")
        if model is None:
            raise ValueError("Нет узла Model в ALP")
        yield "Model", model.findtext("Name", "")
        for obj in model.iter():
            name = obj.findtext("Name", "")
            if name and not name.isdigit():
                yield obj.tag, " ".join([name, obj.findtext("Type", ""), obj.findtext("Description", "")])


def _legacy_name(info):
    if not info.flag_bits & 0x800 and not info.filename.isascii():
        return info.filename.encode("cp437").decode("cp866")
    return info.filename


def build_catalog(paths, db_path):
    """Refresh specified files. Use {'path': ..., 'role': 'lecture'} for primary sources."""
    result = {"indexed": 0, "passages": 0, "missing": [], "errors": []}

    def entry(con, source, container, role, size, state="ok"):
        con.execute("INSERT INTO sources VALUES (?,?,?,?,?)", (source, container, role, size, state))

    def read(con, stream, source, container, name, size, role):
        entry(con, source, container, role, size)
        count = 0
        try:
            for locator, txt in _passages(stream, Path(name).suffix.lower()):
                if txt.strip():
                    con.execute("INSERT INTO passages VALUES (?,?,?,?)", (source, locator, txt.strip(), _fold(txt)))
                    count += 1
        except Exception as exc:
            con.execute("DELETE FROM passages WHERE source=?", (source,))
            con.execute("UPDATE sources SET status=? WHERE source=?", (str(exc), source))
            result["errors"].append({"source": source, "error": str(exc)})
            return
        result["indexed"] += 1
        result["passages"] += count

    with closing(_db(db_path)) as con, con:
        for item in paths:
            role = item.get("role") if isinstance(item, dict) else None
            base = Path(item["path"] if isinstance(item, dict) else item).expanduser().resolve()
            files = (sorted(p for p in base.rglob("*") if p.is_file() and
                            p.suffix.lower() in SUPPORTED and not p.name.startswith("~$"))
                     if base.is_dir() else [base])
            for path in files:
                src = str(path)
                con.execute("DELETE FROM sources WHERE container=? AND role!='generated'", (src,))
                if not path.is_file():
                    entry(con, src, src, _role(path.name, role), 0, "missing")
                    result["missing"].append(src)
                    continue
                if con.execute("SELECT 1 FROM sources WHERE source=? AND role='generated'", (src,)).fetchone():
                    continue
                suffix = path.suffix.lower()
                if suffix == ".rar":
                    from projects import rar_members, relative, unrar
                    entry(con, src, src, "archive", path.stat().st_size)
                    try:
                        for name in rar_members(path):
                            ext = Path(name).suffix.lower()
                            if ext not in DOCUMENTS | {".alp"}:
                                continue
                            member = f"{src}!/{name}"
                            # Read the selected member without extracting neighbouring files.
                            with subprocess.Popen([unrar(), "p", "-inul", "-p-", src, str(relative(name))],
                                                  stdout=subprocess.PIPE) as proc:
                                data = proc.stdout.read(64 * 1024 * 1024 + 1)
                                if len(data) > 64 * 1024 * 1024:
                                    proc.kill()
                                    raise ValueError(f"Больше 64 МиБ: {name}")
                                if proc.wait() != 0:
                                    raise ValueError(f"Не удалось извлечь {name}")
                            read(con, BytesIO(data), member, src, name, len(data), _role(name, role))
                        result["indexed"] += 1
                    except (OSError, ValueError, subprocess.SubprocessError) as exc:
                        con.execute("UPDATE sources SET status=? WHERE source=?", (str(exc), src))
                        result["errors"].append({"source": src, "error": str(exc)})
                    continue
                if suffix != ".zip":
                    with path.open("rb") as f:
                        read(con, f, src, src, path.name, path.stat().st_size, _role(path.name, role))
                    continue
                entry(con, src, src, "archive", path.stat().st_size)
                result["indexed"] += 1
                if path.name.lower().startswith("anylogic "):
                    continue
                try:
                    with ZipFile(path) as z:
                        for info in z.infolist():
                            name = _legacy_name(info)
                            ext = Path(name).suffix.lower()
                            if info.is_dir() or ext not in DOCUMENTS | {".alp", ".mp4"}:
                                continue
                            member = f"{src}!/{name}"
                            if info.file_size > 64 * 1024 * 1024 and ext != ".mp4":
                                entry(con, member, src, _role(name, role), info.file_size, "large")
                                result["errors"].append({"source": member, "error": "Больше 64 МиБ"})
                                continue
                            with z.open(info) as f:
                                stream = BytesIO(f.read()) if ext != ".mp4" else f
                                read(con, stream, member, src, name, info.file_size, _role(name, role))
                except (OSError, RuntimeError, ValueError, BadZipFile) as exc:
                    con.execute("UPDATE sources SET status=? WHERE source=?", (str(exc), src))
                    result["errors"].append({"source": src, "error": str(exc)})
    return result


def list_sources(db_path):
    with closing(_db(db_path)) as con:
        return [dict(r) for r in con.execute("SELECT * FROM sources ORDER BY source")]


def search(db_path, query, limit=12):
    terms = _fold(query).split()
    if not terms:
        return []
    condition = " AND ".join("instr(folded,?)>0" for _ in terms)
    with closing(_db(db_path)) as con:
        rows = con.execute("SELECT source,role,locator,text,folded FROM passages JOIN sources USING(source) WHERE "
                           + condition + " ORDER BY length(folded),source,locator LIMIT ?",
                           (*terms, max(0, int(limit))))
        results = []
        for row in rows:
            text = " ".join(row["text"].split())
            start = max(0, row["folded"].find(terms[0]) - 140)
            snippet = ("…" if start else "") + text[start:start + 500] + ("…" if len(text) > start + 500 else "")
            results.append(dict(source=row["source"], role=row["role"], locator=row["locator"], text=snippet))
        return results


def _identical(con, paragraphs, exclude=None):
    matches = []
    seen = set()
    for paragraph in paragraphs:
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", paragraph):
            literal = _fold(sentence.strip(" \t\r\n.!?"))
            if not literal or literal in seen:
                continue
            seen.add(literal)
            hits = con.execute("""
                SELECT source,role,locator,folded FROM passages JOIN sources USING(source)
                WHERE instr(folded,?)>0 AND role IN ('report','generated','lecture','assignment')
                ORDER BY CASE WHEN role IN ('lecture','assignment') THEN 0 ELSE 1 END
            """, (literal,))
            bounded = re.compile(r"(?<!\w)" + re.escape(literal) + r"(?!\w)")
            for h in hits:
                if h["source"] == exclude or not bounded.search(h["folded"]):
                    continue
                if h["role"] not in {"lecture", "assignment"}:
                    matches.append(dict(sentence=sentence, source=h["source"], locator=h["locator"]))
                break
    return matches


def check_reuse(db_path, paragraphs):
    with closing(_db(db_path)) as con:
        return _identical(con, paragraphs)


def _cover(doc, spec):
    """Retain the reference cover (including logo art), page layout and styles."""
    from docx.oxml.ns import qn
    from docx.table import Table

    def set_text(paragraph, text):
        nodes = paragraph.xpath(".//w:t")
        if not nodes:
            raise ValueError("В шаблоне не найдено поле на титульном листе")
        nodes[0].text = str(text)
        for node in nodes[1:]:
            node.text = ""

    end = title = people = False
    cover_spacing = []
    body = doc.element.body
    for child in list(body):
        if child.tag == qn("w:sectPr"):
            continue
        if end:
            body.remove(child)
            continue
        if child.tag == qn("w:p"):
            line = "".join(child.xpath(".//w:t/text()")).strip()
            if people and not line and not child.xpath(".//w:drawing | .//w:br | .//w:pict"):
                cover_spacing.append(child)
            if "лабораторной работы" in line.casefold():
                set_text(child, f"О выполнении лабораторной работы №{spec['lab']}")
                title = True
            if re.fullmatch(r"Москва\s*[–—-]\s*\d{4}", line):
                set_text(child, f"Москва – {spec.get('year', date.today().year)}")
                end = True
        elif child.tag == qn("w:tbl"):
            for row in Table(child, doc).rows:
                if len(row.cells) != 2 or "студент" not in row.cells[0].text.casefold():
                    continue
                slots = row.cells[1].paragraphs
                if len(slots) < 3:
                    raise ValueError("Не удалось найти реквизиты студента и преподавателя в шаблоне")
                for p, field in zip(slots, ("author", "group", "teacher")):
                    if field in spec:
                        set_text(p._p, spec[field])
                people = True
    if not (end and title and people):
        raise ValueError("Нужен один из образцов отчёта СМВС с титульным листом МИФИ")
    # Allow a wrapped student name while keeping the city and year on the cover.
    for spacer in cover_spacing[1:]:
        body.remove(spacer)
    # Remove unrelated embedded pictures and objects from the deleted report body.
    relns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    kept = {v for node in doc.element.iter() for k, v in node.attrib.items() if k.startswith(relns)}
    for rid, rel in list(doc.part.rels.items()):
        if rel.reltype.rsplit("/", 1)[-1] in {"image", "oleObject", "package", "hyperlink", "chart"} and rid not in kept:
            del doc.part.rels[rid]


def _compose(spec, template, tmp):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH as Align
    from docx.shared import Cm, Pt
    from docx.image.image import Image
    doc = Document(template)
    if template is not None:
        _cover(doc, spec)
    else:
        document_title = doc.add_paragraph(f"Отчёт по лабораторной работе №{spec['lab']}", "Title")
        document_title.alignment = Align.CENTER
        for key, label in (("author","Автор"), ("group","Группа"), ("teacher","Преподаватель")):
            if spec.get(key):
                line = doc.add_paragraph(f"{label} — {spec[key]}")
                line.alignment = Align.CENTER
    props = doc.core_properties
    props.title = str(spec["title"])
    props.author = props.last_modified_by = str(spec["author"])
    props.comments = props.subject = props.keywords = ""
    sec = doc.sections[-1]
    max_width = sec.page_width - sec.left_margin - sec.right_margin
    max_height = sec.page_height - sec.top_margin - sec.bottom_margin - Cm(2.5)

    def paragraph(text, size=12, bold=False, alignment=Align.JUSTIFY):
        p = doc.add_paragraph()
        p.alignment = alignment
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing = 1.15
        if alignment == Align.JUSTIFY:
            p.paragraph_format.first_line_indent = Cm(1.25)
        r = p.add_run(str(text))
        r.bold = bold
        r.font.name, r.font.size = "Times New Roman", Pt(size)
        return p

    first = paragraph(spec["title"], 14, True, Align.CENTER)
    first.paragraph_format.page_break_before = True
    first.paragraph_format.keep_with_next = True
    if spec.get("variant") != "По условию" and str(spec.get("variant", "")).strip():
        paragraph(f"Вариант №{spec['variant']}", alignment=Align.CENTER)
    diagrams = 0
    bodies = []
    for section in spec["sections"]:
        h = paragraph(section["heading"], 12, True, Align.LEFT)
        h.paragraph_format.keep_with_next = True
        lines = section.get("paragraphs", [])
        if not isinstance(lines, list) or any(not isinstance(s, str) or not s.strip() for s in lines):
            raise ValueError("paragraphs должен содержать список непустых абзацев")
        for line in lines:
            bodies.append(line)
            paragraph(line)
        for dataset in section.get("tables", []):
            caption = dataset.get("caption")
            if caption:
                bodies.append(caption)
                paragraph(caption, 10, alignment=Align.LEFT).paragraph_format.keep_with_next = True
            columns = dataset["columns"]
            rows = [columns, *dataset["rows"]]
            if not isinstance(columns, list) or not columns or any(
                    not isinstance(r, list) or len(r) != len(columns) for r in rows):
                raise ValueError("В таблице различается число столбцов")
            table = doc.add_table(rows=0, cols=len(columns))
            table.style = "Table Grid"
            for i, row in enumerate(rows):
                for cell, value in zip(table.add_row().cells, row):
                    r = cell.paragraphs[0].add_run(str(value))
                    r.font.name, r.font.size, r.bold = "Times New Roman", Pt(11), i == 0
        for figure in section.get("figures", []):
            img = Path(figure["path"])
            props_img = Image.from_file(str(img))
            width = min(max_width, int(max_height * props_img.px_width / props_img.px_height))
            p = doc.add_paragraph()
            p.alignment = Align.CENTER
            p.paragraph_format.keep_with_next = True
            p.add_run().add_picture(str(img), width=width)
            diagrams += 1
            bodies.append(figure["caption"])
            paragraph(f"Рисунок {diagrams} – {figure['caption']}", 10, alignment=Align.CENTER)
    doc.save(str(tmp))
    return bodies, diagrams


def write_report(db_path, spec, output_docx):
    """Build a Word report from authored findings and figures, then register its wording."""
    for k in ("title", "author", "group", "lab"):
        if not str(spec.get(k, "")).strip():
            raise ValueError(f"Отсутствует поле {k}")
    sections = spec.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("Нужен список sections")
    if any(not isinstance(s, dict) or not str(s.get("heading", "")).strip() or
           not any(s.get(k) for k in ("paragraphs", "figures", "tables")) for s in sections):
        raise ValueError("В каждом разделе нужен heading и текст, таблица или рисунок")
    if "template" in spec:
        template = Path(spec["template"])
    else:
        candidates = [Path(s["source"]) for s in list_sources(db_path) if s["role"] == "report" and
                      s["source"].lower().endswith(".docx") and Path(s["source"]).is_file()]
        preferred = [p for p in candidates if f"лр{spec['lab']}_" in p.stem.lower()]
        template = (preferred or candidates)[0] if candidates else None
    out = Path(output_docx).resolve()
    if out.suffix.lower() != ".docx":
        raise ValueError("Для отчёта требуется имя с расширением .docx")
    if out.exists():
        raise FileExistsError(f"Укажите новое имя отчёта: {out}")
    out.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=out.parent, suffix=".tmp")
    os.close(fd)
    tmp = Path(name)
    try:
        paragraphs, images = _compose(spec, template, tmp)
        with closing(_db(db_path)) as con, con:
            con.execute("BEGIN IMMEDIATE")
            copies = _identical(con, paragraphs)
            if copies:
                hit = copies[0]
                raise ValueError(f"Повтор формулировки ({hit['source']}, {hit['locator']}): {hit['sentence']}")
            con.execute("DELETE FROM sources WHERE source=? AND role='generated'", (str(out),))
            con.execute("INSERT INTO sources VALUES (?,?,?,?,?)", (str(out), str(out), "generated", tmp.stat().st_size, "ok"))
            con.executemany("INSERT INTO passages VALUES (?,?,?,?)",
                            [(str(out), f"фрагмент {i}", p, _fold(p)) for i, p in enumerate(paragraphs, 1)])
            os.link(tmp, out)
            try:
                con.commit()
            except Exception:
                out.unlink()
                raise
        return dict(output=str(out), template=str(template.resolve()) if template else None, figures=images, sections=len(sections))
    finally:
        tmp.unlink(missing_ok=True)
