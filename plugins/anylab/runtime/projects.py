"""Stage a complete, independent AnyLogic project and publish it atomically."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
import xml.etree.ElementTree as ET


def relative(name):
    path = PureWindowsPath(name)
    if (not path.parts or path.anchor or any(part == ".." or ":" in part or
            part.rstrip(" .") != part or PureWindowsPath(part).is_reserved()
            for part in path.parts)):
        raise ValueError(f"Ожидался относительный путь внутри проекта: {name!r}")
    return Path(*path.parts)


def member_name(info):
    if not info.flag_bits & 0x800:
        try:
            return info.filename.encode("cp437").decode("cp866")
        except UnicodeError:
            pass
    return info.filename


def unrar():
    exe = shutil.which("UnRAR") or Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "WinRAR/UnRAR.exe"
    if not Path(exe).is_file():
        raise FileNotFoundError("Для RAR нужен UnRAR из WinRAR в PATH или Program Files")
    return str(exe)


def rar_members(archive):
    listing = subprocess.check_output([unrar(), "lb", "-scfr", "-p-", str(archive)])
    return [name.replace(chr(92), "/") for name in listing.decode("utf-8-sig").splitlines()]


def select_member(names, member):
    candidates = [name for name in names if name.lower().endswith(".alp")]
    if not member and len(candidates) == 1:
        return candidates[0]
    if member not in candidates:
        raise ValueError(f"Укажите member из списка: {candidates}")
    return member


@contextmanager
def materialize(source, member=None):
    src = Path(source).resolve(strict=True)
    if src.suffix.lower() == ".alp":
        if member:
            raise ValueError("Поле member применимо только к архиву")
        yield src, False
        return
    if src.suffix.lower() == ".rar":
        entries = rar_members(src)
        member = select_member(entries, member)
        parent = member.rpartition("/")[0]
        prefix = parent + "/" if parent else ""
        directories = {p.as_posix() for n in entries for p in Path(n).parents}
        with tempfile.TemporaryDirectory() as td:
            for name in entries:
                if name in directories or not name.startswith(prefix):
                    continue
                dst = Path(td) / relative(name[len(prefix):])
                dst.parent.mkdir(parents=True, exist_ok=True)
                with dst.open("xb") as out:
                    subprocess.run([unrar(), "p", "-inul", "-p-", str(src), str(relative(name))],
                                   stdout=out, check=True)
            yield Path(td) / relative(member[len(prefix):]), True
        return
    if src.suffix.lower() != ".zip":
        raise ValueError("Требуется модель ALP или архив ZIP/RAR с проектом")
    with zipfile.ZipFile(src) as z, tempfile.TemporaryDirectory() as td:
        entries = [(member_name(i), i) for i in z.infolist() if not i.is_dir()]
        member = select_member([name for name, _ in entries], member)
        prefix = member.rpartition("/")[0]
        prefix = prefix + "/" if prefix else ""
        for name, info in entries:
            if not name.startswith(prefix):
                continue
            dst = Path(td) / relative(name[len(prefix):])
            dst.parent.mkdir(parents=True, exist_ok=True)
            with z.open(info) as inp, dst.open("xb") as out:
                shutil.copyfileobj(inp, out)
        yield Path(td) / relative(member[len(prefix):]), True


def installation():
    if os.environ.get("ANYLOGIC_HOME"):
        return Path(os.environ["ANYLOGIC_HOME"])
    base = Path(os.environ.get("ProgramFiles", "C:/Program Files"))
    return next((p for p in sorted(base.glob("AnyLogic*"), reverse=True)
                 if (p / "AnyLogic.exe").is_file()), None)


def copy_atomic(source, target):
    target=Path(target)
    pending=target.with_name(target.name+".tmp")
    shutil.copy2(source,pending)
    pending.replace(target)


def copy_resources(alp, out, archive_project):
    # Archived projects may use unregistered files from Java actions.
    if archive_project:
        shutil.copytree(alp.parent, out, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("*.alp", ".metadata", "*.log"))
    home = installation()
    libraries = sorted(home.glob("plugins/com.anylogic.ui_*/resources"), reverse=True) if home else []
    resources = {}
    for item in ET.parse(alp).findall("./Model/ModelResources/Resource"):
        name = item.findtext("Path")
        if not name or item.findtext("Location", "FILE_SYSTEM") != "FILE_SYSTEM":
            continue
        rel = relative(name)
        target = out / rel
        if target.is_file():
            resources[name] = "archive"
            continue
        roots = [alp.parent]
        if rel.parts[0].casefold() == "3d":
            roots.extend(libraries)
        origin = next((r / rel for r in roots if (r / rel).is_file()), None)
        if not origin:
            raise FileNotFoundError(f"Требуется ресурс {name} для {alp.name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.suffix.lower() == ".dae":
            # COLLADA texture URIs are relative to the mesh itself.
            from urllib.parse import unquote
            images = ET.parse(origin).findall(".//{*}library_images/{*}image/{*}init_from")
            for img in images:
                if img.text and not img.text.startswith("data:"):
                    texture = relative(unquote(img.text.strip()))
                    texture_target = target.parent / texture
                    texture_target.parent.mkdir(parents=True, exist_ok=True)
                    copy_atomic(origin.parent / texture, texture_target)
        copy_atomic(origin, target)
        resources[name] = str(origin)
    return resources


@contextmanager
def new_directory(destination):
    dest = Path(destination).resolve()
    if dest.exists():
        raise FileExistsError(f"Выберите новый каталог: {dest}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dest.parent, prefix=".anylab-") as tmp:
        stage = Path(tmp) / "project"
        stage.mkdir()
        yield stage
        stage.rename(dest)


def create_project(source, destination, spec, member=None):
    import models
    from xml.dom import minidom
    options = dict(spec)
    version = options.pop("target_version", None)
    with materialize(source, member) as (alp, archived), new_directory(destination) as stage:
        resources = copy_resources(alp, stage, archived)
        name = relative(spec.get("model_name") or alp.stem)
        if len(name.parts) != 1 or any(c in name.name for c in '<>"|?*'):
            raise ValueError("Недопустимое имя файла модели")
        target = stage / (str(name) + ".alp")
        changes = models.generate(alp, target, options)
        final_name = relative(changes["name"])
        if len(final_name.parts) != 1 or any(c in final_name.name for c in '<>"|?*'):
            raise ValueError("Недопустимое имя файла модели")
        final_path = stage / (final_name.name + ".alp")
        if final_path != target:
            target.rename(final_path)
            target = final_path
        if version:
            doc = minidom.parse(str(target))
            header = doc.documentElement
            original = header.getAttribute("AlpVersion")
            if original != version:
                if (original, version) != ("8.9.10", "8.9.9"):
                    raise ValueError(f"Нет проверяемого профиля перехода {original} → {version}")
                header.setAttribute("AlpVersion", "8.9.9")
                header.setAttribute("AnyLogicVersion", "8.9.9.202607020720")
                target.write_bytes(doc.toxml(encoding="UTF-8"))
                changes["compatibility_trial"] = {"from": original, "to": version,
                    "status": "requires-build-and-run", "change": "ALP version attributes"}
        manifest = dict(source=str(Path(source).resolve()), source_model=alp.name,
                        member=member, sha256=hashlib.sha256(alp.read_bytes()).hexdigest(),
                        model=target.name, spec=spec, resources=resources, changes=changes)
        (stage / "variant.json").write_text(json.dumps(manifest, ensure_ascii=False,
                indent=2, default=str), encoding="utf-8")
    return {"model": str(Path(destination).resolve() / target.name),
            "manifest": str(Path(destination).resolve() / "variant.json"), "changes": changes}
