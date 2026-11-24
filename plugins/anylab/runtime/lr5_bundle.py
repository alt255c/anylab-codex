"""Build the standard Lab 5 delivery without changing the source projects."""
from pathlib import Path
from tempfile import TemporaryDirectory
import zipfile

from projects import copy_resources

PARTS = ((1, "5.1 Средняя часть"), (2, "5.2 Полный конвейер"))


def input_file(path, suffix):
    item = Path(path).resolve(strict=True)
    if not item.is_file() or item.suffix.casefold() != suffix:
        raise ValueError(f"Ожидался файл {suffix}: {item.name}")
    if item.stat().st_size == 0:
        raise ValueError(f"Пустой файл: {item.name}")
    return item


def bundle_lab5(destination, student, model_1, model_2, video_1, video_2, docx, pdf, capacity, evidence=None):
    """Put two projects and their separate videos under the report and capacity table."""
    if not isinstance(student, str) or not student.strip() or any(c in student for c in '<>:"/\\|?*') or any(ord(c) < 32 for c in student):
        raise ValueError("Укажите фамилию и инициалы как допустимое имя файла")
    import json
    version = json.loads((Path(__file__).resolve().parent.parent / ".codex-plugin/plugin.json").read_text(encoding="utf8"))["version"]
    title = "ЛР5 — " + student.strip()
    folder = title + " — " + version
    destination = Path(destination).resolve()
    if destination.exists() or destination.suffix.casefold() != ".zip":
        raise ValueError("Укажите новый архив .zip")
    models = [input_file(model_1, ".alp"), input_file(model_2, ".alp")]
    videos = [input_file(video_1, ".mp4"), input_file(video_2, ".mp4")]
    if models[0] == models[1] or videos[0] == videos[1]:
        raise ValueError("Для 5.1 и 5.2 нужны отдельные модели и ролики")
    documents = [input_file(docx, ".docx"), input_file(pdf, ".pdf"), input_file(capacity, ".csv")]
    evidence_path = Path(evidence).resolve(strict=True) if evidence else None
    if evidence_path is not None and (not evidence_path.is_dir() or destination.is_relative_to(evidence_path)):
        raise ValueError("Проверка должна быть отдельным каталогом; не помещайте ZIP внутрь него")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as work:
        temporary = Path(work) / destination.name
        with zipfile.ZipFile(temporary, "w", zipfile.ZIP_DEFLATED) as archive:
            for file, name in zip(documents, (title + ".docx", title + ".pdf", "Производительность.csv")):
                archive.write(file, f"{folder}/{name}")
            for index, section in PARTS:
                model = models[index - 1]
                resources = Path(work) / f"resources-{index}"
                resources.mkdir()
                copy_resources(model, resources, False)
                prefix = f"{folder}/{section}"
                archive.write(model, f"{prefix}/{model.name}")
                archive.write(videos[index - 1], f"{prefix}/Демонстрация.mp4", compress_type=zipfile.ZIP_STORED)
                for resource in sorted(resources.rglob("*")):
                    if resource.is_file():
                        archive.write(resource, f"{prefix}/{resource.relative_to(resources).as_posix()}")
            if evidence_path is not None:
                # Only attach the evidence directory the caller explicitly selected.
                for file in sorted(evidence_path.rglob("*")):
                    if file.is_file() and not file.is_symlink() and file.resolve().is_relative_to(evidence_path):
                        archive.write(file, f"{folder}/Проверка/{file.relative_to(evidence_path).as_posix()}")
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError("Не удалось проверить целостность архива")
        temporary.rename(destination)
    return {"archive": str(destination), "folder": folder, "models": 2, "videos": 2}
