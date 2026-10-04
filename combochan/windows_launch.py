"""Launch GUI emulators on the interactive Windows desktop."""
import ctypes
from ctypes import wintypes as w
import subprocess


class StartupInfo(ctypes.Structure):
    _fields_ = [('cb',w.DWORD),('lpReserved',w.LPWSTR),('lpDesktop',w.LPWSTR),
                ('lpTitle',w.LPWSTR),('dwX',w.DWORD),('dwY',w.DWORD),
                ('dwXSize',w.DWORD),('dwYSize',w.DWORD),('dwXCountChars',w.DWORD),
                ('dwYCountChars',w.DWORD),('dwFillAttribute',w.DWORD),
                ('dwFlags',w.DWORD),('wShowWindow',w.WORD),('cbReserved2',w.WORD),
                ('lpReserved2',ctypes.c_void_p),('hStdInput',w.HANDLE),
                ('hStdOutput',w.HANDLE),('hStdError',w.HANDLE)]


class ProcessInfo(ctypes.Structure):
    _fields_ = [('hProcess',w.HANDLE),('hThread',w.HANDLE),
                ('dwProcessId',w.DWORD),('dwThreadId',w.DWORD)]


class VisibleProcess:
    def __init__(self, kernel, handle, pid):
        self.kernel, self.handle, self.pid = kernel, handle, pid
        self.returncode = None

    def poll(self):
        if self.handle:
            result = self.kernel.WaitForSingleObject(self.handle,0)
            if result == 0:
                code = w.DWORD()
                if not self.kernel.GetExitCodeProcess(self.handle,ctypes.byref(code)):
                    raise ctypes.WinError(ctypes.get_last_error())
                self.returncode = code.value
                self.kernel.CloseHandle(self.handle)
                self.handle = None
            elif result == 0xFFFFFFFF:
                raise ctypes.WinError(ctypes.get_last_error())
        return self.returncode

    def __del__(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)


def launch_visible(arguments, cwd):
    kernel = ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateProcessW.argtypes = [w.LPCWSTR,w.LPWSTR,ctypes.c_void_p,
        ctypes.c_void_p,w.BOOL,w.DWORD,ctypes.c_void_p,w.LPCWSTR,
        ctypes.POINTER(StartupInfo),ctypes.POINTER(ProcessInfo)]
    kernel.CreateProcessW.restype = w.BOOL
    kernel.CloseHandle.argtypes = [w.HANDLE]
    kernel.WaitForSingleObject.argtypes = [w.HANDLE,w.DWORD]
    kernel.WaitForSingleObject.restype = w.DWORD
    kernel.GetExitCodeProcess.argtypes = [w.HANDLE,ctypes.POINTER(w.DWORD)]
    startup = StartupInfo()
    startup.cb = ctypes.sizeof(startup)
    startup.lpDesktop = r'winsta0\default'
    startup.dwFlags = 1  # STARTF_USESHOWWINDOW
    startup.wShowWindow = 1  # SW_SHOWNORMAL
    info = ProcessInfo()
    command = ctypes.create_unicode_buffer(subprocess.list2cmdline(arguments))
    if not kernel.CreateProcessW(arguments[0],command,None,None,False,0,None,
                                 str(cwd),ctypes.byref(startup),ctypes.byref(info)):
        raise ctypes.WinError(ctypes.get_last_error())
    kernel.CloseHandle(info.hThread)
    return VisibleProcess(kernel,info.hProcess,info.dwProcessId)
