"""Build and run a trusted ALP through the installed AnyLogic IDE on Windows."""
import argparse
import base64
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import uuid
from xml.dom import Node, minidom


def version(value):
    return tuple(int(n) for n in value.split(".")[:3])


def locate():
    custom = os.environ.get("ANYLOGIC_HOME")
    if custom:
        home = Path(custom).resolve()
        homes = [home.parent if home.is_file() else home]
    else:
        homes = list(Path(os.environ.get("ProgramFiles", "C:/Program Files")).glob("AnyLogic*"))
    choices = []
    for home in homes:
        for plugin in (home / "plugins").glob("com.anylogic.codegen_*"):
            build = plugin.name.partition("_")[2]
            if (home / "AnyLogic.exe").is_file():
                choices.append((version(build), build, home))
    if not choices:
        raise ValueError("AnyLogic.exe не найден. Укажите каталог установки в ANYLOGIC_HOME.")
    _, build, home = max(choices)
    return home, build


def direct(parent, tag):
    return [n for n in parent.childNodes if n.nodeType == Node.ELEMENT_NODE and n.tagName == tag]


def content(node):
    return "".join(n.data for n in node.childNodes if n.nodeType in (Node.TEXT_NODE, Node.CDATA_SECTION_NODE))


def field(parent, tag):
    nodes = direct(parent, tag)
    return content(nodes[0]) if nodes else ""


def put(parent, tag, value):
    nodes = direct(parent, tag)
    node = nodes[0] if nodes else parent.appendChild(parent.ownerDocument.createElement(tag))
    while node.firstChild:
        node.removeChild(node.firstChild)
    node.appendChild(parent.ownerDocument.createCDATASection(value))


def hook(experiment, tag, code):
    put(experiment, tag, field(experiment, tag) + "\n" + code + "\n")


def mark(path):
    literal = json.dumps(str(path), ensure_ascii=False)
    # One writer per phase; CREATE_NEW preserves the first start during parallel replications.
    return ("try { java.nio.file.Files.writeString(java.nio.file.Path.of(" + literal
            + "), Long.toString(ProcessHandle.current().pid()), java.nio.file.StandardOpenOption.CREATE_NEW); } "
            + "catch (java.nio.file.FileAlreadyExistsException ignoredAnyLab) {} "
            + "catch (java.io.IOException ioAnyLab) { throw new RuntimeException(ioAnyLab); }")


def isolate_package(model, token):
    old = field(model, "JavaPackageName")
    if not old:
        raise ValueError("Модель должна содержать JavaPackageName.")
    package = old + "_anylab_" + token
    qualified = re.compile(r"(?<![\w$])" + re.escape(old) + r"(?=\.)")
    for node in model.getElementsByTagName("*"):
        if node.tagName in {"JavaPackageName", "PackageName"} and content(node) == old:
            put(node.parentNode, node.tagName, package)
            continue
        # Java references in code and serialized identifiers may be package-qualified.
        if node.tagName in {"JavaClassName", "ClassName", "Code", "Imports", "Import"} or node.tagName.endswith("Code"):
            for text in node.childNodes:
                if text.nodeType in (Node.CDATA_SECTION_NODE, Node.TEXT_NODE):
                    text.data = qualified.sub(package, text.data)
    return package


def metrics_hook(ex, out, raw, token, root_type):
    metrics = json.loads(raw)
    if not isinstance(metrics, dict) or not metrics or not all(
            isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip() for k, v in metrics.items()):
        raise ValueError("--metrics требует JSON-объект с названиями и числовыми выражениями Java.")
    path = out / "metrics.csv"
    with path.open("x", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow(metrics)
    root = "((" + root_type + ")getEngine().getRoot())"
    values = ["Double.toString((double)(" + root + "." + expr + "))" for expr in metrics.values()]
    code = ('synchronized ("anylab_' + token + '".intern()) { try { java.nio.file.Files.writeString('
            + 'java.nio.file.Path.of(' + json.dumps(str(path), ensure_ascii=False) + '), '
            + 'String.join(",", ' + ', '.join(values) + ') + "\\n", java.nio.file.StandardOpenOption.APPEND); '
            + '} catch(java.io.IOException ioAnyLab) { throw new RuntimeException(ioAnyLab); } }')
    hook(ex, "AfterSimulationRunCode", code)


def prepare(args, out, result, build, token):
    src = Path(args.model).resolve(strict=True)
    raw = src.read_bytes()
    doc = minidom.parseString(raw)
    root = doc.documentElement
    result.update(model=str(src), sha256=hashlib.sha256(raw).hexdigest(),
                  model_version=root.getAttribute("AlpVersion"), ide_version=build)
    if version(result["model_version"]) > version(build):
        if version(result["model_version"])[:2] != version(build)[:2]:
            raise ValueError(f"ALP {result['model_version']} новее IDE {build}. Нужна совместимая установка AnyLogic.")
        original = result["model_version"]
        root.setAttribute("AnyLogicVersion", build)
        root.setAttribute("AlpVersion", ".".join(build.split(".")[:3]))
        result["source_model_version"] = original
        result["compatibility_adjustment"] = f"Подготовлена копия ALP для AnyLogic {build}; исходный файл не изменён."
    model = direct(root, "Model")[0]
    container = direct(model, "Experiments")[0]
    choices = [e for e in container.childNodes if e.nodeType == Node.ELEMENT_NODE]
    named = [e for e in choices if field(e, "Name") == args.experiment]
    if len(named) != 1:
        raise ValueError("Эксперименты модели: " + ", ".join(field(e, "Name") for e in choices))
    ex = named[0]
    is_simulation = ex.tagName == "SimulationExperiment"
    if ex.tagName not in ("SimulationExperiment", "ParamVariationExperiment", "OptimizationExperiment", "MonteCarloExperiment"):
        raise ValueError("Обработчики запуска не настроены для " + ex.tagName)
    project = "AnyLab_" + token
    result.update(project=project, experiment=args.experiment, experiment_type=ex.tagName)
    put(model, "Name", project)
    result["java_package"] = isolate_package(model, token)
    active_classes = direct(model, "ActiveObjectClasses")
    root_class = next((c for c in direct(active_classes[0], "ActiveObjectClass")
                       if field(c, "Name") == "Main"), None) if active_classes else None
    if root_class is None:
        raise ValueError("Не удалось определить корневой класс Main для сбора метрик")
    root_type = result["java_package"] + "." + field(root_class, "Name")
    folder = out / "model"
    folder.mkdir()
    rels = {content(p) for resource in direct(model, "ModelResources")
            for entry in direct(resource, "Resource") for p in direct(entry, "Path")}
    for path in ("3d", "database", *args.asset):
        if (src.parent / path).exists() or path in args.asset:
            rels.add(path)
    for name in sorted(rels):
        if not name.strip():
            continue
        rel = Path(name)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("Ресурс должен находиться в каталоге проекта: " + name)
        source = (src.parent / rel).resolve()
        dest = (folder / rel).resolve()
        if not source.is_relative_to(src.parent) or not dest.is_relative_to(folder) or source == src.parent:
            raise ValueError("Проверьте путь ресурса: " + name)
        if source == folder or source in folder.parents:
            raise ValueError("Каталог запуска пересекается с ресурсом: " + name)
        dest.parent.mkdir(exist_ok=True, parents=True)
        if source.is_dir():
            shutil.copytree(source, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(source, dest)
    put(ex, "VmArgs", field(ex, "VmArgs") + " -Danylab.run=" + token)
    try:
        try:
            from .console_capture import agent_jar
        except ImportError:
            from console_capture import agent_jar
        home,_=locate()
        jar=agent_jar(home)
        if jar and str(jar).isascii():
            console=out/"console.log"
            encoded = base64.urlsafe_b64encode(str(console).encode("utf8")).decode("ascii")
            put(ex,"VmArgs",field(ex,"VmArgs")+' "-javaagent:'+str(jar)+'=utf8:'+encoded+'"')
            result["console_log"]=str(console)
    except (OSError,subprocess.SubprocessError) as error:
        result["console_capture_error"]=str(error)
    pp = direct(ex, "PresentationProperties")
    if pp:
        old = field(pp[0], "Title")
        put(pp[0], "Title", f"{old or args.experiment} [{project}]")
    hook(ex, "InitialSetupCode", mark(out / "ready.pid"))
    # A queued IDE request can wake up after the client timeout or interrupt.
    cancelled = json.dumps(str(out / "cancelled"), ensure_ascii=False)
    hook(ex, "InitialSetupCode", "if (java.nio.file.Files.exists(java.nio.file.Path.of(" +
         cancelled + "))) { throw new IllegalStateException(\"AnyLab: cancelled\"); }")
    hook(ex, "BeforeSimulationRunCode", mark(out / "started.pid"))
    if args.metrics:
        metrics_hook(ex, out, args.metrics, token, root_type)
        result["metrics_csv"] = str(out / "metrics.csv")
    if is_simulation:
        status_path=json.dumps(str(out / "engine-state.json"),ensure_ascii=False)
        hook(ex,"AfterSimulationRunCode",'try { java.nio.file.Files.writeString(java.nio.file.Path.of('+status_path+'), "{\\\"state\\\":\\\""+getEngine().getState()+"\\\",\\\"time\\\":"+getEngine().time()+"}"); } catch(java.io.IOException e) { throw new RuntimeException(e); }')
    hook(ex, "AfterSimulationRunCode" if is_simulation else "AfterExperimentCode", mark(out / "finished.pid"))
    if is_simulation:
        put(ex, "BypassInitialScreen", "true")
    else:
        hook(ex, "InitialSetupCode", "run();")
    path = folder / (project + ".alp")
    path.write_bytes(doc.toxml(encoding="utf-8"))
    result["instrumented_model"] = str(path)
    return path


def runtime_pid(out):
    for phase in ["started", "ready", "finished"]:
        try:
            return int((out / (phase + ".pid")).read_text(encoding="ascii"))
        except (FileNotFoundError, ValueError):
            continue
    return None


def close_owned(token):
    # Restrict cleanup to Java runtimes bearing this invocation's unique VM argument.
    command = ("$p=Get-CimInstance Win32_Process -Filter \"Name='javaw.exe' OR Name='java.exe'\" "
               "| Where-Object { $_.CommandLine -match '(?<!\\S)-Danylab[.]run=" + token + "(?=\\s|$)' }; "
               "foreach ($item in $p) { $proc=Get-Process -Id $item.ProcessId -ErrorAction SilentlyContinue; "
               "if ($proc -and [Math]::Abs(($proc.StartTime-$item.CreationDate).TotalSeconds) -lt 1) "
               "{ $proc.Kill(); $proc.WaitForExit(5000) | Out-Null; $item.ProcessId } }")
    proc = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
                          capture_output=True, text=True, timeout=20, check=True)
    return [int(line) for line in proc.stdout.split() if line.isdigit()]

def close_run_tree(evidence):
    """Kill only the isolated IDE and processes owned by this AnyLab run."""
    token = evidence["project"].removeprefix("AnyLab_")
    if not re.fullmatch(r"[0-9a-f]{12}", token):
        raise ValueError("Неверный идентификатор прогона AnyLab")
    ide_pid = evidence.get("owned_ide_pid")
    if ide_pid:
        # PID alone can be reused. The command line also has to name this run.
        script = (
            f'$item=Get-CimInstance Win32_Process -Filter "ProcessId={int(ide_pid)}"; '
            f'if ($item.Name -eq "AnyLogic.exe" -and $item.CommandLine -like "*AnyLab_{token}.alp*") '
            '{ & taskkill.exe /T /F /PID $item.ProcessId 2>$null | Out-Null }'
        )
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, timeout=20, check=False)
    closed = close_owned(token)
    browser_profile = evidence.get("owned_browser_profile")
    if browser_profile:
        # A browser can outlive its Java parent. Match the entire isolated profile,
        # never a regular Chrome process or an explicitly shared IDE workspace.
        script = (
            "$profile=$env:ANYLAB_OWNED_BROWSER_PROFILE; "
            "$items=Get-CimInstance Win32_Process | Where-Object Name -eq 'chrome.exe'; "
            "foreach ($item in $items) { "
            "if ($item.CommandLine -and $item.CommandLine.IndexOf($profile, "
            "[StringComparison]::OrdinalIgnoreCase) -ge 0) { "
            "& taskkill.exe /T /F /PID $item.ProcessId 2>$null | Out-Null } }"
        )
        env = {**os.environ, "ANYLAB_OWNED_BROWSER_PROFILE": browser_profile}
        subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                       capture_output=True, timeout=20, check=False, env=env)
    return closed


def build_paths(project):
    workspace = os.environ.get("ANYLAB_IDE_WORKSPACE")
    if workspace:
        yield Path(workspace).resolve() / (project + "_BUILD")
        return
    for folder in Path.home().glob(".AnyLogic*/Workspace*/" + project + "_BUILD"):
        yield folder


def isolated_workspace(out):
    return Path(os.environ.get("ANYLAB_IDE_WORKSPACE") or Path(out) / "ide-workspace").resolve()


def save_result(out, result):
    temp = out / "result.tmp"
    temp.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(out / "result.json")


def run(args):
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    if any(out.iterdir()):
        raise ValueError("Для нового запуска нужен пустой каталог --out.")
    # Exclusive creation also prevents concurrent runners sharing this directory.
    token = uuid.uuid4().hex[:12]
    with (out / "run.id").open("x", encoding="ascii") as f:
        f.write(token)
    start = time.monotonic()
    result = dict(state="preparing", compiled=False, started=False, finished=False,
                  runtime_pid=None, until=args.until, timeout_seconds=args.timeout)
    launched = False
    try:
        # Always isolate generated Eclipse projects from the user's workspace.
        # Restoring many old AnyLab projects there can break IDE startup.
        os.environ["ANYLAB_IDE_WORKSPACE"] = str(isolated_workspace(out))
        home, build = locate()
        model = prepare(args, out, result, build, token)
        project = result["project"]
        command = [str(home / "AnyLogic.exe")]
        workspace = os.environ.get("ANYLAB_IDE_WORKSPACE")
        if workspace:
            command.extend(["-data",str(Path(workspace).resolve())])
        ide_process = subprocess.Popen([*command, "-r", str(model), args.experiment],
                         cwd=home, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if workspace:
            result["owned_ide_pid"] = ide_process.pid
            if Path(workspace).resolve() == out / "ide-workspace":
                result["owned_browser_profile"] = str(out / "ide-workspace" / "chromium" / "userData")
        launched = True
        result["state"] = "waiting"
        save_result(out, result)
        while time.monotonic() - start < args.timeout:
            pid = runtime_pid(out)
            if pid:
                result.update(runtime_pid=pid, compiled=True)
            for phase in ("started", "finished"):
                if not result[phase] and (out / (phase + ".pid")).is_file():
                    result[phase] = True
                    result[phase + "_seconds"] = round(time.monotonic() - start, 3)
            if (out / "engine-state.json").is_file():
                try:
                    engine_state=json.loads((out/"engine-state.json").read_text(encoding="utf-8"))
                    result["engine_state"]=engine_state["state"]
                    result["model_time_reached"]=engine_state["time"]
                    if engine_state["state"]=="ERROR":
                        result.update(state="runtime_error",finished=False,error="AnyLogic engine entered ERROR; the end callback does not prove successful completion.")
                        break
                except (ValueError,KeyError):
                    pass
            if result[args.until]:
                result["state"] = "finished" if result["finished"] else "started"
                break
            time.sleep(0.2)
        else:
            result.update(state="timeout", error="Истёк срок ожидания обработчика эксперимента. Проверьте панель Ошибки в IDE.")
        for folder in build_paths(project):
            sources = list((folder / "src.generated").rglob("*.java"))
            classes = list((folder / "classes").rglob("*.class"))
            result.update(java_directory=str(folder / "src.generated"), java_files=len(sources),
                          class_directory=str(folder / "classes"), class_files=len(classes))
        if result["started"] and result["finished"]:
            seconds = (out / "finished.pid").stat().st_mtime - (out / "started.pid").stat().st_mtime
            result["simulation_seconds"] = round(max(0.0, seconds), 6)
    except (Exception, KeyboardInterrupt) as exc:
        result.update(state="error", error=str(exc) or type(exc).__name__)
    finally:
        if launched and (args.close or result["state"] in {"timeout", "error", "runtime_error"}):
            if result["state"] in {"timeout", "error"}:
                (out / "cancelled").touch()
            try:
                result["closed_runtime_pids"] = close_run_tree(result)
            except (OSError, subprocess.SubprocessError) as exc:
                result["cleanup_error"] = str(exc)
            if result.get("owned_ide_pid") and ide_process.poll() is None:
                ide_process.terminate()
                ide_process.wait(timeout=20)
        result["elapsed_seconds"] = round(time.monotonic() - start, 3)
        save_result(out, result)
    print(json.dumps(result, ensure_ascii=False))
    # Cleanup is best-effort after a completed experiment. A PowerShell/CIM
    # failure must not turn a successful Java compile and simulation into a
    # failed run; retain the diagnostic in result.json for inspection.
    return 0 if result["state"] in {"started", "finished"} else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    cmds = parser.add_subparsers(dest="cmd", required=True)
    cmds.add_parser("doctor")
    p = cmds.add_parser("run")
    p.add_argument("model")
    p.add_argument("--experiment", default="Simulation")
    p.add_argument("--out", required=True)
    p.add_argument("--until", choices=["started", "finished"], default="started")
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--close", action="store_true")
    p.add_argument("--asset", action="append", default=[], metavar="RELATIVE_PATH")
    p.add_argument("--metrics", help="JSON: столбец -> числовое Java-выражение в контексте root")
    cmds.add_parser("windows")
    for command in ["capture", "record"]:
        p = cmds.add_parser(command)
        p.add_argument("--window", type=lambda s: int(s, 0), required=True, metavar="HWND")
        p.add_argument("--out", required=True)
        if command == "record":
            p.add_argument("--seconds", type=int, default=20)
            p.add_argument("--fps", type=int, default=20)
            p.add_argument("--profile", choices=["window", "hd", "light"], default="window")
    args = parser.parse_args()
    if args.cmd == "run":
        if not 1 <= args.timeout <= 900:
            parser.error("--timeout: 1..900 секунд")
        return run(args)
    home, build = locate()
    if args.cmd == "doctor":
        import media
        print(json.dumps(dict(home=str(home), build=build, python=sys.version.split()[0],
                              pillow=bool(importlib.util.find_spec("PIL")),
                              ffmpeg=media.find_encoder()),
                         ensure_ascii=False))
        return 0
    import media
    return media.command(args, home)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError, ImportError, subprocess.SubprocessError) as exc:
        print(json.dumps({"state": "error", "error": str(exc)}, ensure_ascii=False))
        sys.exit(2)
