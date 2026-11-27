"""Local browser interface for the AnyLab Studio workflow."""
import argparse
import csv
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import threading
from urllib.parse import quote, urlsplit
import uuid
import webbrowser

from studio_build import MEASUREMENTS, METRO_CAMERA_PROFILE, STATION_CAMERA_PROFILE, build, build_steps, catalog, config_from, save_json
from studio_codex import AssistantHandoff
from studio_process import BuildProcess

ASSETS = Path(__file__).with_name("studio_assets")
JOB_ID = r"[0-9a-f]{32}"


def run_job(path):
    if sys.stdin.buffer.read(1)!=b"1":
        return
    status=json.loads(path.read_text(encoding="utf-8"))
    mode=status["mode"]

    def note(message):
        status["message"]=message
        save_json(path,status)

    def progress(key, state, count=None, total=None, csv_path=None):
        step=status.setdefault("steps",{}).setdefault(key,{})
        step["state"]=state
        if total is not None:
            step.update(count=count,total=total,csv=str(csv_path) if csv_path else None)
        if state=="done" and "total" in step:
            step.update(count=step["total"],csv=None)
        save_json(path,status)

    try:
        result=build(status["config"],path.parent/"Результат",note,prepare_only=mode=="prepare",
                     preview_only=mode in {"preview","cashier_preview"},
                     preview_part="6.2" if mode=="cashier_preview" else None,progress=progress)
        message={"complete":"Комплект готов к скачиванию","preview":"Предпросмотр готов",
                 "prepared":"Модели подготовлены"}[result["state"]]
        status.update(state=result["state"],message=message,result=result)
    except AssistantHandoff as pending:
        status.update(state="assistant_required",message=str(pending),assistant_request=pending.prompt)
    except Exception as error:
        status.update(state="error",message=str(error))
    save_json(path,status)


class Jobs:
    def __init__(self, directory):
        self.root = Path(directory).expanduser().resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.lock = threading.Lock()
        self.active = None
        self.worker = None

    def status(self, key):
        path = self.root / key / "Статус.json"
        if not path.is_file():
            raise KeyError(key)
        status = json.loads(path.read_text(encoding="utf-8"))
        status.setdefault("created",datetime.fromtimestamp(path.stat().st_mtime,timezone.utc).isoformat())
        if status["state"]=="running" and self.active!=key:
            status.update(state="interrupted",message="Сборку можно продолжить с сохранённых этапов")
        if (status["state"]=="preview" and status["config"]["lab"]=="6"
                and status.get("result",{}).get("camera_profile")!=STATION_CAMERA_PROFILE):
            status.update(state="stale_preview",message="Сохранённый предпросмотр АЗС сделан до последних изменений. Обновите предпросмотр 6.2.")
            status.pop("result",None)
        if (status["state"]=="preview" and status["config"]["lab"]=="4"
                and status.get("result",{}).get("camera_profile")!=METRO_CAMERA_PROFILE):
            status.update(state="stale_preview",message="Предпросмотр ЛР4 устарел. Запустите новый, чтобы увидеть текущие стены и пассажиропоток.")
            status.pop("result",None)
        return status

    def presentation(self, status):
        result=status.copy()
        config=status["config"]
        mode=status.get("mode") or ("preview" if status["state"] in {"preview","stale_preview"} else
                                   "prepare" if status["state"]=="prepared" else "full")
        workspace=self.root/status["id"]/"Результат"
        file=workspace/"Рабочие файлы"/"Готовые этапы.json"
        try:
            saved=json.loads(file.read_text(encoding="utf-8")) if file.is_file() else {}
        except OSError:
            saved={}
        steps=[]
        for key,label in build_steps(config,mode):
            stage=status.get("steps",{}).get(key,{}).copy()
            current=stage.get("state","pending")
            if not stage:
                if key=="models":
                    done=any(name=="Модели" or name.startswith("Модели ЛР4") for name in saved)
                elif key.endswith(" · видео"):
                    done=any(name.startswith(key[:3]+" · MP4") for name in saved)
                elif key.endswith(" · кадры"):
                    done=any(name.startswith(key[:3]+" · кадры") for name in saved)
                else:
                    done=key in saved or (key=="report" and (workspace/"Отчёт.pdf").is_file())
                if done:
                    current="done"
                elif status["state"] in {"error","interrupted"} and key.replace(" — "," · ") in status["message"]:
                    current="paused"
            if status["state"] in {"complete","prepared","preview","stale_preview"}:
                current="done"
            if current=="active" and status["state"]!="running":
                current="paused"
            csv_path=stage.get("csv")
            count,total=stage.get("count"),stage.get("total")
            if current=="paused" and not stage and key.startswith("4.2 — "):
                from hashlib import sha256
                from itertools import product
                from studio_grid import read_grid, saved_rows
                experiment=key.split(" — ",1)[1]
                metrics=dict(MEASUREMENTS["4.2"])[experiment]
                source=next((Path(value["4.2"]).resolve() for value in saved.values()
                             if isinstance(value,dict) and isinstance(value.get("4.2"),str)),None)
                if source and source.is_file() and source.is_relative_to(workspace):
                    _,_,axes=read_grid(source,experiment,metrics)
                    expected=list(product(*(axis[2] for axis in axes)))
                    rows=saved_rows(source,experiment,metrics,file.parent,sha256(source.read_bytes()).hexdigest(),
                                    [axis[1] for axis in axes],expected)
                    count,total=len(rows),len(expected)
            if csv_path and Path(csv_path).resolve().is_relative_to(workspace):
                try:
                    with Path(csv_path).open(encoding="utf-8-sig",newline="") as stream:
                        count=min(total,count+sum(None not in row and all(row.values()) for row in csv.DictReader(stream)))
                except (OSError,ValueError):
                    pass
            steps.append({"label":label,"state":current,"count":count,"total":total})
        result["steps"]=steps
        result["config"]={key:value for key,value in config.items() if key!="photo"}
        return result

    def recent(self):
        paths=(p/"Статус.json" for p in self.root.iterdir() if re.fullmatch(JOB_ID,p.name))
        present=[p for p in paths if p.is_file()]
        history=[]
        for path in sorted(present,key=lambda p:p.stat().st_mtime,reverse=True):
            try:
                status=self.status(path.parent.name)
            except (OSError,ValueError,KeyError):
                continue
            config=status["config"]
            history.append({"id":status["id"],"state":status["state"],"created":status["created"],
                            "config":{key:config.get(key,"") for key in ("lab","student","group","variant")}})
        return history

    def begin(self, config, mode, key=None):
        with self.lock:
            if self.active:
                raise RuntimeError("Дождитесь завершения текущей сборки")
            created=datetime.now(timezone.utc).isoformat()
            if key is None:
                key=uuid.uuid4().hex
                config=config_from(config)
            else:
                previous=self.status(key)
                created=previous["created"]
                if previous["state"] not in {"prepared","preview","stale_preview","assistant_required","error","interrupted","cancelled"}:
                    raise ValueError("Эту сборку уже можно скачать")
                config=previous["config"]
                if previous["state"] in {"assistant_required","cancelled"}:
                    mode=previous.get("mode","full")
            directory=self.root/key
            directory.mkdir(exist_ok=True)
            status={"id":key,"state":"running","message":"Подготовка шаблонов","config":config,"mode":mode,
                    "created":created}
            path=directory/"Статус.json"
            save_json(path,status)
            try:
                worker=BuildProcess([sys.executable,str(Path(__file__).resolve()),"--worker",str(path)])
            except OSError as error:
                status.update(state="error",message=f"Не удалось запустить задачу AnyLab: {error}")
                save_json(path,status)
                return status.copy()
            self.active=key
            self.worker=worker

            def monitor():
                code=worker.process.wait()
                with self.lock:
                    if self.worker is not worker:
                        return
                    worker.close()
                    try:
                        current=self.status(key)
                        if current["state"]=="running":
                            current.update(state="error",message=f"Процесс сборки завершился досрочно (код {code})")
                            save_json(path,current)
                    finally:
                        self.active=self.worker=None
            threading.Thread(target=monitor,daemon=True).start()
            return status.copy()

    def cancel(self,key):
        with self.lock:
            if key!=self.active:
                return self.status(key)
            self.worker.close()
            try:
                self.worker.process.wait(timeout=10)
            except subprocess.TimeoutExpired as error:
                raise RuntimeError("AnyLab ещё завершает процессы") from error
            current=self.status(key)
            try:
                if current["state"]=="running":
                    current.update(state="cancelled",message="Сборка остановлена. Готовые этапы сохранены.")
                    save_json(self.root/key/"Статус.json",current)
            finally:
                self.active=self.worker=None
            return current

    def delete(self,key):
        with self.lock:
            if key==self.active:
                raise RuntimeError("Остановите сборку перед удалением")
            self.status(key)
            source=self.root/key
            if source.resolve()!=source or source.resolve().parent!=self.root:
                raise ValueError("Каталог сборки находится вне истории")
            discarded=self.root/(".deleted-"+uuid.uuid4().hex)
            source.rename(discarded)
        shutil.rmtree(discarded)


def handler(jobs, token, authority):
    class Request(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def headers_for(self, status, mime, length):
            self.send_response(status)
            self.send_header("Content-Type",mime)
            self.send_header("Content-Length",str(length))
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Referrer-Policy","no-referrer")
            self.send_header("Content-Security-Policy","default-src 'self'; img-src 'self' blob:; frame-ancestors 'none'; form-action 'self'")

        def result(self, data, status=HTTPStatus.OK, mime="application/json; charset=utf-8"):
            content=data if isinstance(data,bytes) else json.dumps(data,ensure_ascii=False).encode()
            self.headers_for(status,mime,len(content))
            self.end_headers()
            self.wfile.write(content)

        def check(self, authenticated):
            if self.headers.get("Host")!=authority:
                self.result({"error":"Откройте локальный адрес AnyLab"},HTTPStatus.FORBIDDEN)
                return False
            if authenticated and self.headers.get("X-AnyLab-Token")!=token:
                self.result({"error":"Обновите страницу AnyLab Studio"},HTTPStatus.FORBIDDEN)
                return False
            return True

        def do_GET(self):
            path=urlsplit(self.path).path
            if not self.check(path.startswith("/api/")):
                return
            assets={"/":("index.html","text/html"),"/studio.css":("studio.css","text/css"),
                    "/studio.js":("studio.js","text/javascript")}
            if path in assets:
                name,mime=assets[path]
                data=(ASSETS/name).read_bytes().replace(b"__ANYLAB_TOKEN__",token.encode())
                self.result(data,mime=mime+"; charset=utf-8")
                return
            if path=="/api/catalog":
                self.result(catalog())
                return
            if path=="/api/jobs":
                self.result(jobs.recent())
                return
            photo=re.fullmatch(fr"/api/jobs/({JOB_ID})/photos/(4\.1|4\.2|5\.1|5\.2|6\.1|6\.2)/(\d)",path)
            if photo:
                try:
                    status=jobs.status(photo[1])
                    index=int(photo[3])
                    label=f"Ракурс {index}" if index else "План"
                    image=status["result"]["photos"][photo[2]][label]
                    root=jobs.root/photo[1]/"Результат"/"Проверка"
                    source=Path(image).resolve(strict=True)
                    if not source.is_relative_to(root) or source.suffix.lower()!=".png":
                        raise KeyError(path)
                    self.result(source.read_bytes(),mime="image/png")
                    return
                except (KeyError,FileNotFoundError):
                    self.result({"error":"Кадр отсутствует"},HTTPStatus.NOT_FOUND)
                    return
            match=re.fullmatch(fr"/api/jobs/({JOB_ID})(/archive)?",path)
            if match:
                try:
                    status=jobs.status(match[1])
                    if not match[2]:
                        self.result(jobs.presentation(status))
                        return
                    archive=jobs.root/match[1]/"Результат"/"Комплект.zip"
                    if status["state"]!="complete" or not archive.is_file():
                        raise KeyError(path)
                    filename=quote(f"ЛР{status['config']['lab']} — Комплект.zip")
                    self.headers_for(HTTPStatus.OK,"application/zip",archive.stat().st_size)
                    self.send_header("Content-Disposition",f"attachment; filename*=UTF-8''{filename}")
                    self.end_headers()
                    with archive.open("rb") as stream:
                        shutil.copyfileobj(stream,self.wfile)
                    return
                except KeyError:
                    pass
            self.result({"error":"Файл или сборка отсутствует"},HTTPStatus.NOT_FOUND)

        def do_POST(self):
            if not self.check(True):
                return
            if self.headers.get("Origin") not in (None,f"http://{authority}"):
                self.result({"error":"Недопустимый источник"},HTTPStatus.FORBIDDEN)
                return
            try:
                path=urlsplit(self.path).path
                retry=re.fullmatch(fr"/api/jobs/({JOB_ID})/resume",path)
                cashier=re.fullmatch(fr"/api/jobs/({JOB_ID})/cashier-preview",path)
                cancel=re.fullmatch(fr"/api/jobs/({JOB_ID})/cancel",path)
                remove=re.fullmatch(fr"/api/jobs/({JOB_ID})/delete",path)
                if remove:
                    jobs.delete(remove[1])
                    self.result({"deleted":True})
                    return
                if cancel:
                    self.result(jobs.cancel(cancel[1]))
                    return
                if retry:
                    status=jobs.begin(None,"full",retry[1])
                elif cashier:
                    if jobs.status(cashier[1])["config"]["lab"]!="6":
                        raise ValueError("Предпросмотр кассы доступен для ЛР6")
                    status=jobs.begin(None,"cashier_preview",cashier[1])
                elif path=="/api/jobs":
                    size=int(self.headers.get("Content-Length","0"))
                    if self.headers.get_content_type()!="application/json" or not 0<size<=2_820_000:
                        raise ValueError("Ожидаются настройки в формате JSON")
                    request=json.loads(self.rfile.read(size))
                    if not isinstance(request,dict):
                        raise ValueError("Ожидается объект настроек")
                    mode=request.get("mode","full")
                    if mode not in ("full","prepare","preview"):
                        raise ValueError("Неизвестный режим")
                    status=jobs.begin(request.get("config"),mode)
                else:
                    self.result({"error":"Такой операции нет"},HTTPStatus.NOT_FOUND)
                    return
                self.result(status,HTTPStatus.ACCEPTED)
            except KeyError:
                self.result({"error":"Сборка отсутствует"},HTTPStatus.NOT_FOUND)
            except (RuntimeError,OSError) as error:
                self.result({"error":str(error)},HTTPStatus.CONFLICT)
            except ValueError as error:
                self.result({"error":str(error)},HTTPStatus.BAD_REQUEST)
    return Request


def serve(output, port=0, open_browser=True, ready=None):
    jobs=Jobs(output)
    token=secrets.token_urlsafe(32)
    with ThreadingHTTPServer(("127.0.0.1",port),BaseHTTPRequestHandler) as server:
        authority=f"127.0.0.1:{server.server_port}"
        server.RequestHandlerClass=handler(jobs,token,authority)
        url="http://"+authority+"/"
        if ready:
            save_json(Path(ready),{"url":url,"output":str(jobs.root)})
        else:
            print(url,flush=True)
        if open_browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        finally:
            if jobs.active:
                jobs.cancel(jobs.active)


def open_studio(destination):
    """Start the local server without tying its lifetime to the MCP request."""
    import os
    import subprocess
    import sys
    import tempfile
    import time
    parent=Path(destination).expanduser().resolve()
    parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        ready=Path(scratch)/"ready.json"
        options={"creationflags":subprocess.CREATE_NO_WINDOW} if os.name=="nt" else {"start_new_session":True}
        process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),"--output",str(parent),
                                  "--ready",str(ready),"--no-browser"],stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,**options)
        try:
            for _ in range(80):
                if ready.is_file():
                    return json.loads(ready.read_text(encoding="utf-8"))
                if process.poll() is not None:
                    break
                time.sleep(.1)
        except Exception:
            process.terminate()
            raise
        if process.poll() is None:
            process.terminate()
        raise RuntimeError("Не удалось запустить AnyLab Studio")


if __name__=="__main__":
    parser=argparse.ArgumentParser(description="AnyLab Studio")
    parser.add_argument("--output",type=Path,default=Path.cwd()/"AnyLab Studio")
    parser.add_argument("--port",type=int,default=0)
    parser.add_argument("--no-browser",action="store_true")
    parser.add_argument("--worker",type=Path,help=argparse.SUPPRESS)
    parser.add_argument("--ready",type=Path,help=argparse.SUPPRESS)
    args=parser.parse_args()
    if args.worker:
        run_job(args.worker)
    else:
        serve(args.output,args.port,not args.no_browser,args.ready)
