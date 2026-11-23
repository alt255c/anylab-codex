"""Target-window capture for AnyLogic IDE and its Chromium animation windows."""
import ctypes as c
import hashlib
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import time
import uuid


user = c.WinDLL("user32", use_last_error=True)
gdi = c.WinDLL("gdi32", use_last_error=True)
kernel = c.WinDLL("kernel32", use_last_error=True)


def bind(lib, name, result, *args):
    f = getattr(lib, name)
    f.argtypes = args
    f.restype = result
    return f


handle = w.HANDLE
ptr = c.c_void_p
get_dc = bind(user, "GetWindowDC", handle, w.HWND)
release_dc = bind(user, "ReleaseDC", c.c_int, w.HWND, handle)
mem_dc = bind(gdi, "CreateCompatibleDC", handle, handle)
bitmap = bind(gdi, "CreateCompatibleBitmap", handle, handle, c.c_int, c.c_int)
select = bind(gdi, "SelectObject", handle, handle, handle)
delete = bind(gdi, "DeleteObject", w.BOOL, handle)
delete_dc = bind(gdi, "DeleteDC", w.BOOL, handle)
dib = bind(gdi, "GetDIBits", c.c_int, handle, handle, w.UINT, w.UINT, ptr, ptr, w.UINT)
render = bind(user, "PrintWindow", w.BOOL, w.HWND, handle, w.UINT)
get_pid = bind(user, "GetWindowThreadProcessId", w.DWORD, w.HWND, c.POINTER(w.DWORD))
open_process = bind(kernel, "OpenProcess", handle, w.DWORD, w.BOOL, w.DWORD)
close = bind(kernel, "CloseHandle", w.BOOL, handle)
query_path = bind(kernel, "QueryFullProcessImageNameW", w.BOOL, handle, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD))
get_rect = bind(user, "GetWindowRect", w.BOOL, w.HWND, c.POINTER(w.RECT))
get_client = bind(user, "GetClientRect", w.BOOL, w.HWND, c.POINTER(w.RECT))
client_screen = bind(user, "ClientToScreen", w.BOOL, w.HWND, c.POINTER(w.POINT))


def process_path(pid):
    h = open_process(0x1000, False, pid)
    if not h:
        return None
    try:
        buf = c.create_unicode_buffer(32768)
        size = w.DWORD(len(buf))
        if query_path(h, 0, buf, c.byref(size)):
            return Path(buf.value)
    finally:
        close(h)


def windows(home):
    found = []
    enum_fn = c.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)

    @enum_fn
    def visit(hwnd, data):
        n = user.GetWindowTextLengthW(hwnd)
        if n <= 0 or not user.IsWindowVisible(hwnd):
            return True
        pid = w.DWORD()
        get_pid(hwnd, c.byref(pid))
        exe = process_path(pid.value)
        if exe is None or not exe.is_relative_to(home):
            return True
        title = c.create_unicode_buffer(n + 1)
        user.GetWindowTextW(hwnd, title, n + 1)
        found.append(dict(hwnd=hwnd, pid=pid.value, title=title.value, executable=exe.name))
        return True

    user.EnumWindows(visit, 0)
    return found


def frame(hwnd, pid):
    # PW_RENDERFULLCONTENT includes Chromium's composited client surface.
    owner = w.DWORD()
    get_pid(hwnd, c.byref(owner))
    if owner.value != pid:
        raise ValueError("Восстановите окно AnyLogic и проверьте HWND.")
    if user.IsIconic(hwnd):
        # IDE launches or a desktop focus change can minimize the animation.
        # Restore only the already verified target HWND, never a different app.
        restore=bind(user,"ShowWindowAsync",w.BOOL,w.HWND,c.c_int)
        restore(hwnd,9)
        time.sleep(.3)
        if user.IsIconic(hwnd):
            raise ValueError("Не удалось восстановить выбранное окно AnyLogic.")
    rect, client, origin = w.RECT(), w.RECT(), w.POINT()
    if not (get_rect(hwnd, c.byref(rect)) and get_client(hwnd, c.byref(client))
            and client_screen(hwnd, c.byref(origin))):
        raise OSError("Не удалось прочитать границы окна.")
    width, height = rect.right - rect.left, rect.bottom - rect.top
    if width <= 0 or height <= 0 or width * height > 32_000_000:
        raise ValueError("Размер окна не подходит для записи.")
    dc = get_dc(hwnd)
    if not dc:
        raise OSError("GetWindowDC")
    mem = bmp = old = None
    try:
        mem = mem_dc(dc)
        bmp = bitmap(dc, width, height)
        if not (mem and bmp):
            raise OSError("CreateCompatibleBitmap")
        old = select(mem, bmp)
        if not render(hwnd, mem, 2):
            raise OSError("Windows не смогла отрисовать окно.")
        select(mem, old)
        old = None
        header = c.create_string_buffer(struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0))
        pixels = c.create_string_buffer(width * height * 4)
        if dib(mem, bmp, 0, height, pixels, header, 0) != height:
            raise OSError("GetDIBits")
    finally:
        if old:
            select(mem, old)
        if bmp:
            delete(bmp)
        if mem:
            delete_dc(mem)
        release_dc(hwnd, dc)
    from PIL import Image
    image = Image.frombytes("RGB", (width, height), pixels.raw, "raw", "BGRX")
    x, y = origin.x - rect.left, origin.y - rect.top
    return image.crop((x, y, x + client.right, y + client.bottom))


def find_encoder():
    exe = os.environ.get("ANYLAB_FFMPEG") or shutil.which("ffmpeg")
    if exe:
        return str(exe) if Path(exe).is_file() else None
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except (ImportError, RuntimeError):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
        for root in (base / "Python", base / "Programs/Python"):
            files = sorted(root.glob("*/Lib/site-packages/imageio_ffmpeg/binaries/ffmpeg*.exe"))
            if files:
                return str(files[-1])
    return None


def encoder():
    exe = find_encoder()
    if not exe:
        raise ValueError("Установите imageio-ffmpeg или задайте ANYLAB_FFMPEG")
    return exe


def record(hwnd, pid, first, path, seconds, fps):
    width, height = first.size
    cmd = [encoder(), "-hide_banner", "-loglevel", "error", "-n", "-f", "rawvideo",
           "-pixel_format", "rgb24", "-video_size", f"{width}x{height}", "-framerate", str(fps),
           "-i", "pipe:0", "-an", "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264",
           "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-crf", "19", "-movflags", "+faststart", str(path)]
    process = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    try:
        start = time.monotonic()
        current = first
        for index in range(seconds * fps):
            due = start + index / fps
            if index:
                if time.monotonic() <= due + 1 / fps:
                    time.sleep(max(0.0, due - time.monotonic()))
                    current = frame(hwnd, pid)
                    if current.size != first.size:
                        # DPI/desktop changes can resize a Chromium client while
                        # it is being captured. Keep one canvas and the entire
                        # image, preserving aspect ratio instead of stretching
                        # it or discarding an otherwise valid demonstration.
                        from PIL import ImageOps, Image
                        current = ImageOps.pad(current,first.size,
                                               method=Image.Resampling.LANCZOS,
                                               color="white")
            process.stdin.write(current.tobytes())
        process.stdin.close()
        if process.wait(timeout=30):
            raise RuntimeError("FFmpeg завершился с ошибкой.")
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def command(args, home):
    try:
        user.SetProcessDpiAwarenessContext(c.c_void_p(-4))
    except AttributeError:
        user.SetProcessDPIAware()
    rows = windows(home)
    if args.cmd == "windows":
        print(json.dumps(rows, ensure_ascii=False))
        return 0
    window = next((r for r in rows if r["hwnd"] == args.window), None)
    if not window:
        raise ValueError("HWND отсутствует в выводе windows для выбранной установки AnyLogic.")
    out = Path(args.out).resolve()
    suffix = ".mp4" if args.cmd == "record" else ".png"
    if out.suffix.lower() != suffix or out.exists():
        raise ValueError("Укажите новый файл с расширением " + suffix)
    out.parent.mkdir(exist_ok=True, parents=True)
    temp = out.with_name("." + uuid.uuid4().hex + suffix)
    try:
        shot = frame(args.window, window["pid"])
        if shot.width < 4 or shot.height < 4 or all(lo == hi for lo, hi in shot.getextrema()):
            raise ValueError("Windows вернула пустой кадр. Восстановите окно и дождитесь анимации.")
        if args.cmd == "record":
            if not (1 <= args.seconds <= 900 and 1 <= args.fps <= 60):
                raise ValueError("Допустимая длительность 1..900 секунд, частота 1..60 кадров/с.")
            record(args.window, window["pid"], shot, temp, args.seconds, args.fps)
        else:
            shot.save(temp, "PNG")
        temp.rename(out)
        if args.cmd == "capture":
            out.with_name(out.name + ".capture.json").write_text(json.dumps({
                "kind": "anylogic-window-capture", "file": str(out),
                "sha256": hashlib.sha256(out.read_bytes()).hexdigest(),
                "window": window, "dimensions": shot.size,
            }, ensure_ascii=False, indent=2), encoding="utf8")
    finally:
        temp.unlink(missing_ok=True)
    print(json.dumps(dict(file=str(out), window=window, dimensions=shot.size), ensure_ascii=False))
    return 0
