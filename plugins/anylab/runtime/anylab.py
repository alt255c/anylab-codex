"""Local CLI and MCP stdio entry point for the AnyLogic lab assistant."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import shutil
import time

BASE = Path(__file__).resolve().parent
CATALOG = Path(os.environ.get("ANYLAB_DB", Path(os.environ.get("LOCALAPPDATA", Path.home())) / "AnyLabCodex" / "course.sqlite3"))
BRIDGE = BASE / "bridge" / "anylogic.py"


def dumps(value):
    return json.dumps(value, ensure_ascii=False, default=str, allow_nan=False)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def index_sources(paths=None):
    import materials
    paths = [{"path": str(BASE / "assignments"), "role": "assignment"}] + (paths or [])
    result = materials.build_catalog(paths, CATALOG)
    import course_tasks
    course_tasks.refresh(CATALOG)
    return result


def inspect_model(source, member=None):
    import models
    from projects import materialize
    with materialize(source, member) as (model, _):
        return models.inspect_model(model)


def native(args, *, result_path=None):
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    proc = subprocess.run([sys.executable, "-X", "utf8", str(BRIDGE), *map(str, args)],
                          encoding="utf-8", errors="replace", capture_output=True, env=env)
    if result_path and Path(result_path).is_file():
        data = load_json(result_path)
    else:
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            data = {"stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}
    if proc.returncode:
        raise RuntimeError(dumps(data) + (" " + proc.stderr[-1200:] if proc.stderr.strip() else ""))
    return data


def task_data(lab=None, variant=None):
    records = [t for t in load_json(BASE / "data/assignments.json") if lab is None or t["lab"] == lab]
    if variant is not None:
        for task in records:
            options = task.pop("variants")
            task["available_variants"] = list(sorted(options, key=int))
            task["variant_data"] = options.get(variant)
    elif lab is None:
        return [{"lab": number, "variants": sorted({v for t in records if t["lab"] == number
                 for v in t["variants"]},key=int), "assignments": [t["title"] for t in records
                 if t["lab"] == number]} for number in sorted({t["lab"] for t in records})]
    for task in records:
        task["official_pdf"] = str(BASE / "assignments" / task["source"])
    return records


def template_root(root=None):
    configured = root or os.environ.get("ANYLAB_TEMPLATES")
    if configured:
        folder = Path(configured).resolve(strict=True)
    else:
        candidates = [Path.cwd() / "AnyLab-private-templates",
                      Path.cwd() / "outputs/AnyLab-private-templates"]
        folder = next((p for p in candidates if (p / "templates.json").is_file()), None)
    if folder is None or not (folder / "templates.json").is_file():
        raise FileNotFoundError("Укажите папку локального комплекта с templates.json через root или ANYLAB_TEMPLATES")
    return folder


def templates(lab, root=None):
    folder = template_root(root)
    entry = load_json(folder / "templates.json").get(str(lab))
    if not entry:
        raise ValueError(f"Нет лабораторной {lab} в каталоге шаблонов")
    if entry["report"]:
        entry["report"] = str(folder / entry["report"])
    if entry.get("report_fields"):
        entry["report_fields"] = str(folder / entry["report_fields"])
    for items in entry["models"].values():
        for item in items:
            if item["kind"] == "alp":
                item["file"] = str(folder / item["file"])
                if item.get("fields"):
                    item["fields"] = str(folder / item["fields"])
    return entry


def stage_template(lab, task, destination, model=1, root=None):
    from projects import new_directory
    options = templates(lab, root)["models"].get(task, [])
    if not 1 <= model <= len(options) or options[model - 1]["kind"] != "alp":
        raise ValueError(f"Готовый ALP для {task} в этом комплекте отсутствует")
    source = Path(options[model - 1]["file"]).resolve(strict=True)
    if not source.is_relative_to(template_root(root)):
        raise ValueError("Модель должна находиться внутри комплекта")
    with new_directory(destination) as stage:
        shutil.copytree(source.parent, stage, dirs_exist_ok=True)
    return {"model": str(Path(destination).resolve() / source.name), "template": str(source)}


def fill_model(lab, task, destination, values, model=1, root=None):
    from tempfile import TemporaryDirectory
    from projects import create_project, new_directory
    from template_fill import patch_model
    with TemporaryDirectory() as working, new_directory(destination) as output:
        info = stage_template(lab, task, Path(working) / "template", model=model, root=root)
        source = Path(info["model"])
        patch_model(source, values.get("block_code", {}))
        options = values.get("spec", {})
        generated = create_project(source, Path(working) / "generated", options)
        shutil.copytree(Path(working) / "generated", output, dirs_exist_ok=True)
        for resource in source.parent.iterdir():
            target = output / resource.name
            if resource.is_dir():
                shutil.copytree(resource,target,dirs_exist_ok=True)
            elif resource != source and not resource.name.endswith(".fill.json") and not target.exists():
                shutil.copy2(resource,target)
    return {"model": str(Path(destination).resolve() / Path(generated["model"]).name),
            "template": info["template"]}


def examples(query="",limit=20):
    from projects import installation
    host = installation()
    if host is None:
        return []
    base = Path(os.environ.get("ProgramData", "C:/ProgramData")) / host.name / "eclipse/plugins"
    if not 1 <= limit <= 100:
        raise ValueError("limit must be 1–100")
    return [str(p) for p in sorted(base.glob("com.anylogic.examples_*/**/*.alp"))
            if all(word.casefold() in p.stem.casefold() for word in query.split())][:limit]


def video(model, destination, seconds=20, three_d=True):
    from video_demo import record_demo
    if not 3 <= seconds <= 120:
        raise ValueError("Длительность записи должна быть от 3 до 120 секунд")
    root = Path(destination).resolve()
    root.mkdir(parents=True, exist_ok=False)
    record_demo(Path(model).resolve(strict=True), root, root, seconds, three_d, 3)
    return {"video": str(root / "demo.mp4")}


def run_model(model, destination, experiment, timeout=720, until="finished", close=False, metrics=None):
    if until not in {"started", "finished"}:
        raise ValueError("until: started или finished")
    if not 1 <= timeout <= 900:
        raise ValueError("timeout: 1–900 секунд")
    out = Path(destination)
    if out.exists() and (not out.is_dir() or any(out.iterdir())):
        raise FileExistsError(f"Укажите пустой каталог запуска: {out}")
    args = ["run", Path(model).resolve(strict=True), "--experiment", experiment, "--out", destination,
            "--timeout", timeout, "--until", until]
    if close:
        args.append("--close")
    if metrics:
        args.extend(["--metrics", dumps(metrics)])
    return native(args, result_path=Path(destination) / "result.json")


def calibrated_run(source, destination, experiment, minutes=12, member=None, metrics=None, keep_final_open=False):
    from experiments import budget
    seconds = 60 * float(minutes)
    if not math.isfinite(seconds) or not 0 < seconds <= 900:
        raise ValueError("Укажите бюджет до 15 минут")
    dest = Path(destination).resolve()
    dest.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    def remaining():
        left = int(seconds - (time.monotonic() - started))
        if left < 1:
            raise TimeoutError("Время истекло до запуска следующего этапа")
        return left
    pilot = budget(source, dest / "pilot", experiment, minutes, member=member)
    tick = time.monotonic()
    evidence = run_model(pilot["model"], dest / "pilot-run", experiment, remaining(), close=True,
                         metrics=metrics)
    measured = time.monotonic() - tick
    sim = max(.20, float(evidence.get("simulation_seconds", measured)))
    overhead = max(0.0, measured - sim)
    plan = budget(source, dest / "planned", experiment, remaining() / 60, sim,
                  member=member, overhead_seconds=overhead)
    run = run_model(plan["model"], dest / "run", experiment, remaining(), close=not keep_final_open, metrics=metrics)
    return {"pilot_wall_seconds": round(measured, 2), "plan": plan, "run": run,
            "total_seconds": round(time.monotonic() - started, 2)}


def dispatch(action, params):
    from pdf_export import export_pdf
    from template_fill import fill_report
    import experiments
    import materials
    import projects
    functions = {
        "tasks": task_data,
        "templates": templates,
        "stage_template": stage_template,
        "fill_model": fill_model,
        "fill_report": fill_report,
        "examples": examples,
        "video": video,
        "index": index_sources,
        "sources": lambda: materials.list_sources(CATALOG),
        "search": lambda query, limit=12: materials.search(CATALOG, query, limit),
        "inspect": inspect_model,
        "generate": projects.create_project,
        "budget": experiments.budget,
        "calibrate": calibrated_run,
        "run": run_model,
        "report": lambda spec, destination: materials.write_report(CATALOG, spec, destination),
        "pdf": export_pdf,
        "check_text": lambda paragraphs: materials.check_reuse(CATALOG, paragraphs),
        "doctor": lambda: native(["doctor"]),
        "windows": lambda: native(["windows"]),
        "capture": lambda window, destination: native(["capture", "--window", window, "--out", destination]),
        "record": lambda window, destination, seconds=20: native(["record", "--window", window,
                                     "--out", destination, "--seconds", seconds]),
    }
    if action not in functions:
        raise ValueError(f"Неизвестная команда {action!r}")
    if isinstance(params.get("source"), str) and "!/" in params["source"]:
        params = dict(params)
        src, member = params["source"].split("!/", 1)
        if params.get("member", member) != member:
            raise ValueError("Указаны разные пути внутри архива")
        params.update(source=src, member=member)
    return functions[action](**params)


# One schema is shared by the CLI and the tool discovery endpoint.
COMMANDS = {
    "tasks": ("Список лабораторных и вариантов или условия всех заданий указанной работы.", (), {"lab":"integer","variant":"string"}),
    "templates": ("Показать локальные образцы всех заданий и общий шаблон DOCX по лабораторной.", ("lab",), {"lab":"integer","root":"string"}),
    "stage_template": ("Скопировать готовую модель ALP и её ресурсы в новый рабочий каталог.", ("lab","task","destination"), {"lab":"integer","task":"string","destination":"string","model":"integer","root":"string"}),
    "fill_model": ("Заполнить переменные и свойства блоков в копии готового ALP.", ("lab","task","destination","values"),
                   {"lab":"integer","task":"string","destination":"string","values":"object","model":"integer","root":"string"}),
    "fill_report": ("Заполнить поля, таблицы и места для снимков в готовом DOCX.", ("template","destination","values"),
                    {"template":"string","destination":"string","values":"object"}),
    "examples": ("Найти установленные примеры AnyLogic (по словам в английском названии).", (), {"query":"string","limit":"integer"}),
    "video": ("Открыть покадровый показ модели и записать MP4 в новый каталог.", ("model","destination"), {"model":"string","destination":"string","seconds":"integer","three_d":"boolean"}),
    "index": ("Обновить индекс материалов. По умолчанию берётся список из sources.json.", (), {"paths":"array"}),
    "sources": ("Показать доступные и отсутствующие материалы, включая модели внутри архивов.", (), {}),
    "search": ("Найти фрагменты материалов и координаты источников.", ("query",), {"query":"string", "limit":"integer"}),
    "inspect": ("Прочитать структуру ALP, имена элементов, параметры, геометрию и эксперименты.", ("source",), {"source":"string", "member":"string"}),
    "generate": ("Создать вариант модели и ресурсы в новом каталоге. Настройки описаны в README.", ("source","destination","spec"),
                 {"source":"string", "member":"string", "destination":"string", "spec":"object"}),
    "budget": ("Подготовить копию для пилота либо применить его замер к числу прогонов.", ("source","destination","experiment"),
               {"source":"string","destination":"string","experiment":"string","minutes":"number","pilot_seconds":"number","overhead_seconds":"number","member":"string"}),
    "calibrate": ("Выполнить пилот и затем серию в общем бюджете до 15 минут.", ("source","destination","experiment"),
               {"source":"string","destination":"string","experiment":"string","minutes":"number","member":"string","metrics":"object"}),
    "run": ("Собрать и запустить эксперимент через AnyLogic. until=started или finished.", ("model","destination","experiment"),
            {"model":"string","destination":"string","experiment":"string","timeout":"integer","until":"string","close":"boolean","metrics":"object"}),
    "windows": ("Получить идентификаторы окон для захвата.", (), {}),
    "capture": ("Сохранить снимок выбранного окна в PNG.", ("window","destination"), {"window":"string","destination":"string"}),
    "record": ("Записать окно демонстрации в MP4.", ("window","destination"), {"window":"string","destination":"string","seconds":"integer"}),
    "check_text": ("Проверить предложения по образцам, истории и первичным материалам.", ("paragraphs",), {"paragraphs":"array"}),
    "report": ("Создать DOCX по образцу, спецификации и снимкам.", ("spec","destination"), {"spec":"object","destination":"string"}),
    "pdf": ("Экспортировать DOCX в PDF. Движок auto, word, libreoffice или reportlab.", ("source","destination"), {"source":"string","destination":"string","engine":"string"}),
    "doctor": ("Проверить наличие AnyLogic и средств захвата.", (), {}),
}


def tools_list():
    return [{"name": name, "description": description, "inputSchema": {
        "type": "object", "properties": {k: {"type": v} for k, v in fields.items()},
        "required": list(required), "additionalProperties": False}}
        for name, (description, required, fields) in COMMANDS.items()]


def mcp():
    versions = ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05")
    for line in sys.stdin.buffer:
        msg = {}
        try:
            msg = json.loads(line)
            method = msg["method"]
            if "id" not in msg:
                continue
            p = msg.get("params", {})
            if method == "initialize":
                version = p.get("protocolVersion")
                result = {"protocolVersion": version if version in versions else versions[0],
                          "capabilities": {"tools": {}}, "serverInfo": {"name":"anylab","version":"1.0"}}
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": tools_list()}
            elif method == "resources/list":
                result = {"resources": []}
            elif method == "resources/templates/list":
                result = {"resourceTemplates": []}
            elif method == "tools/call":
                try:
                    data = dispatch(p["name"], p.get("arguments", {}))
                    result = {"content": [{"type":"text","text":dumps(data)}]}
                except Exception as err:
                    result = {"isError": True, "content": [{"type":"text","text":str(err)}]}
            else:
                raise LookupError(method)
            reply = {"result": result}
        except Exception as err:
            reply = {"error":{"code": -32601 if isinstance(err, LookupError) else -32600,
                              "message": str(err)}}
        reply.update(jsonrpc="2.0", id=msg.get("id") if isinstance(msg, dict) else None)
        print(dumps(reply), flush=True)


def json_arg(value):
    return load_json(value[1:]) if value.startswith("@") else json.loads(value)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    cli = argparse.ArgumentParser(description="Локальная мастерская моделей AnyLogic")
    subs = cli.add_subparsers(dest="action", required=True)
    subs.add_parser("serve", help="MCP-сервер по stdio")
    for action, (description, required, fields) in COMMANDS.items():
        cmd = subs.add_parser(action, help=description, description=description)
        for key, kind in fields.items():
            kwargs = {"required": key in required, "default": argparse.SUPPRESS}
            if kind == "boolean":
                kwargs["action"] = "store_true"
            else:
                kwargs["type"] = {"string":str,"integer":int,"number":float,"array":json_arg,"object":json_arg}[kind]
            cmd.add_argument("--" + key.replace("_","-"), **kwargs)
    params = vars(cli.parse_args())
    action = params.pop("action")
    if action == "serve":
        mcp()
        return
    try:
        print(json.dumps(dispatch(action, params), ensure_ascii=False, indent=2, default=str))
    except Exception as err:
        print(dumps({"error": str(err)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
