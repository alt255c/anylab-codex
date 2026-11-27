"""Own all subprocesses of one Studio build, including AnyLogic and FFmpeg."""

import os
import signal
import subprocess


def windows_job(pid):
    import ctypes
    from ctypes import wintypes

    class BasicLimits(ctypes.Structure):
        _fields_=[("ProcessTime",ctypes.c_longlong),("JobTime",ctypes.c_longlong),
                  ("Flags",wintypes.DWORD),("MinWorkingSet",ctypes.c_size_t),
                  ("MaxWorkingSet",ctypes.c_size_t),("ActiveProcesses",wintypes.DWORD),
                  ("Affinity",ctypes.c_size_t),("Priority",wintypes.DWORD),("Scheduling",wintypes.DWORD)]

    class ExtendedLimits(ctypes.Structure):
        _fields_=[("Basic",BasicLimits),("Io",ctypes.c_ulonglong*6),
                  ("ProcessMemory",ctypes.c_size_t),("JobMemory",ctypes.c_size_t),
                  ("PeakProcessMemory",ctypes.c_size_t),("PeakJobMemory",ctypes.c_size_t)]

    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.CreateJobObjectW.argtypes=(wintypes.LPVOID,wintypes.LPCWSTR)
    kernel.CreateJobObjectW.restype=wintypes.HANDLE
    kernel.OpenProcess.argtypes=(wintypes.DWORD,wintypes.BOOL,wintypes.DWORD)
    kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.SetInformationJobObject.argtypes=(wintypes.HANDLE,ctypes.c_int,wintypes.LPVOID,wintypes.DWORD)
    kernel.AssignProcessToJobObject.argtypes=(wintypes.HANDLE,wintypes.HANDLE)
    kernel.CloseHandle.argtypes=(wintypes.HANDLE,)
    job=kernel.CreateJobObjectW(None,None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        limits=ExtendedLimits()
        limits.Basic.Flags=0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(job,9,ctypes.byref(limits),ctypes.sizeof(limits)):
            raise ctypes.WinError(ctypes.get_last_error())
        handle=kernel.OpenProcess(0x101,False,pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not kernel.AssignProcessToJobObject(job,handle):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            kernel.CloseHandle(handle)
    except BaseException:
        kernel.CloseHandle(job)
        raise
    return lambda:kernel.CloseHandle(job)


class BuildProcess:
    def __init__(self, command):
        options={"creationflags":subprocess.CREATE_NO_WINDOW} if os.name=="nt" else {"start_new_session":True}
        self.process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL,**options)
        self.close_job=None
        try:
            if os.name=="nt":
                self.close_job=windows_job(self.process.pid)
            # The worker waits for this byte before launching any subprocesses.
            with self.process.stdin as gate:
                gate.write(b"1")
        except BaseException:
            self.close()
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait()
            raise

    def close(self):
        if self.close_job is not None:
            close,self.close_job=self.close_job,None
            close()
        elif os.name!="nt":
            try:
                os.killpg(self.process.pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
