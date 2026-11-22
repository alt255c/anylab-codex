"""PDF export with native converters and a Python fallback."""
from io import BytesIO
from pathlib import Path
import os
import shutil
import subprocess
import tempfile
from xml.sax.saxutils import escape


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, timeout=90,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), **kwargs)
    if result.returncode:
        output = result.stderr.decode("utf-8", "replace").strip()
        raise RuntimeError(output[-500:] or f"Код выхода {result.returncode}")


def word(source, target):
    script = target.parent / "word-export.vbs"
    script.write_text("""Option Explicit
Dim word, doc, exportError
Set word = CreateObject("Word.Application")
word.DisplayAlerts = 0
word.AutomationSecurity = 3
On Error Resume Next
Set doc = word.Documents.Open(WScript.Arguments(0), False, True, False)
If Err.Number = 0 Then doc.ExportAsFixedFormat WScript.Arguments(1), 17
exportError = Err.Number
If exportError <> 0 Then WScript.StdErr.WriteLine Err.Description
If IsObject(doc) Then doc.Close 0
word.Quit 0
If exportError <> 0 Then WScript.Quit 1
""",encoding="ascii")
    run(["cscript.exe", "//Nologo", "//B", str(script), str(source), str(target)])


def libreoffice(source, target):
    program = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    candidates = [shutil.which("soffice.com"), shutil.which("soffice"), program/"LibreOffice/program/soffice.com"]
    office = next((str(p) for p in candidates if p and Path(p).is_file()), None)
    if not office:
        raise FileNotFoundError("LibreOffice не найден")
    run([office, "-env:UserInstallation=" + (target.parent / "profile").as_uri(),
         "--headless", "--convert-to", "pdf:writer_pdf_Export", "--outdir", str(target.parent), str(source)])


def python_pdf(source, target):
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph as WordParagraph
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Table as PdfTable, TableStyle

    fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
    pdfmetrics.registerFont(TTFont("AnyLab", str(fonts/"arial.ttf")))
    pdfmetrics.registerFont(TTFont("AnyLabBold", str(fonts/"arialbd.ttf")))
    doc = Document(source)
    style = ParagraphStyle("body", fontName="AnyLab", fontSize=10, leading=13, spaceAfter=6)
    heading = ParagraphStyle("head", parent=style, fontName="AnyLabBold", fontSize=12, leading=15)
    story = []
    for node in doc.element.body:
        if node.tag.endswith("}p"):
            p = WordParagraph(node, doc)
            if story and (p.paragraph_format.page_break_before or p._p.xpath(".//w:br[@w:type='page']")):
                story.append(PageBreak())
            if p.text.strip():
                is_heading = p.style.name.startswith(("Heading", "Title")) or all(r.bold for r in p.runs if r.text.strip())
                story.append(Paragraph(escape(p.text.strip()).replace("\n","<br/>"),heading if is_heading else style))
            for rel in p._p.xpath(".//a:blip/@r:embed"):
                part = doc.part.related_parts.get(rel)
                if part is None:
                    continue
                image = Image(BytesIO(part.blob))
                scale = min(470/image.imageWidth,360/image.imageHeight)
                image.drawWidth, image.drawHeight = image.imageWidth*scale, image.imageHeight*scale
                story.append(image)
        elif node.tag.endswith("}tbl"):
            table = Table(node, doc)
            rows = [[Paragraph(escape(cell.text).replace("\n", "<br/>"),style) for cell in row.cells]
                    for row in table.rows]
            if rows:
                pdf_table=PdfTable(rows,colWidths=[470/len(rows[0])]*len(rows[0]))
                pdf_table.setStyle(TableStyle([("VALIGN",(0,0),(-1,-1),"TOP"),
                                               ("GRID",(0,0),(-1,-1),0.3,colors.grey)]))
                story.append(pdf_table)
    if not story:
        raise ValueError("В DOCX отсутствует содержимое для PDF")
    SimpleDocTemplate(str(target),pagesize=A4,rightMargin=60,leftMargin=60).build(story)


def export_pdf(source, destination, engine="auto"):
    from pypdf import PdfReader
    source = Path(source).resolve(strict=True)
    dest = Path(destination).resolve()
    engines = {"word":word,"libreoffice":libreoffice,"reportlab":python_pdf}
    if source.suffix.lower() != ".docx" or dest.suffix.lower() != ".pdf":
        raise ValueError("Ожидаются входной DOCX и выходной PDF")
    if engine not in ("auto", *engines):
        raise ValueError("engine: auto, word, libreoffice или reportlab")
    if dest.exists():
        raise FileExistsError(f"Укажите новое имя PDF: {dest}")
    dest.parent.mkdir(parents=True,exist_ok=True)
    errors = []
    for key in engines if engine == "auto" else (engine,):
        with tempfile.TemporaryDirectory(dir=dest.parent) as tmp:
            pdf = Path(tmp) / (source.stem + ".pdf")
            try:
                engines[key](source,pdf)
                pages = len(PdfReader(pdf).pages)
                if pages == 0:
                    raise RuntimeError("Пустой PDF")
            except Exception as exc:
                errors.append(f"{key}: {exc}")
                continue
            os.link(pdf,dest)
            return dict(output=str(dest),pages=pages,engine=key,
                        layout="reflowed" if key=="reportlab" else "native")
    raise RuntimeError("Экспорт PDF завершился ошибкой. " + " | ".join(errors))
