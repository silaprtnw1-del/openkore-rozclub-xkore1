#define UNICODE
#define _UNICODE
#include <windows.h>
#include <stdio.h>
#include <wchar.h>

static int fail(const wchar_t *step)
{
    fwprintf(stderr, L"[ERROR] %ls failed (Win32=%lu)\n", step, GetLastError());
    return 1;
}

int wmain(int argc, wchar_t **argv)
{
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    wchar_t target[MAX_PATH];
    wchar_t dll[MAX_PATH];
    wchar_t workdir[MAX_PATH];
    wchar_t command[(MAX_PATH * 2) + 8];
    wchar_t *slash;
    SIZE_T dllBytes;
    SIZE_T written = 0;
    LPVOID remoteDll = NULL;
    HANDLE remoteThread = NULL;
    DWORD remoteModule = 0;

    if (argc != 3) {
        fwprintf(stderr, L"Usage: roz-xkore-launcher.exe Ragnarok.exe NetRedirect.dll\n");
        return 2;
    }
    if (!GetFullPathNameW(argv[1], MAX_PATH, target, NULL))
        return fail(L"GetFullPathName(target)");
    if (!GetFullPathNameW(argv[2], MAX_PATH, dll, NULL))
        return fail(L"GetFullPathName(dll)");
    if (GetFileAttributesW(target) == INVALID_FILE_ATTRIBUTES) {
        SetLastError(ERROR_FILE_NOT_FOUND);
        return fail(L"Ragnarok.exe lookup");
    }
    if (GetFileAttributesW(dll) == INVALID_FILE_ATTRIBUTES) {
        SetLastError(ERROR_FILE_NOT_FOUND);
        return fail(L"NetRedirect DLL lookup");
    }

    wcscpy_s(workdir, MAX_PATH, target);
    slash = wcsrchr(workdir, L'\\');
    if (slash)
        *slash = L'\0';
    _snwprintf_s(command, _countof(command), _TRUNCATE, L"\"%ls\"", target);

    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);
    if (!CreateProcessW(NULL, command, NULL, NULL, FALSE, 0,
                        NULL, workdir, &si, &pi))
        return fail(L"CreateProcess");

    wprintf(L"Ragnarok.exe started, pid = %lu\n", pi.dwProcessId);
    /* Let the native loader resolve the main executable's imports before
       inspecting and patching its IAT. */
    WaitForInputIdle(pi.hProcess, 15000);
    dllBytes = (wcslen(dll) + 1) * sizeof(wchar_t);
    remoteDll = VirtualAllocEx(pi.hProcess, NULL, dllBytes,
                               MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!remoteDll)
        goto inject_failed;
    if (!WriteProcessMemory(pi.hProcess, remoteDll, dll, dllBytes, &written)
        || written != dllBytes)
        goto inject_failed;

    remoteThread = CreateRemoteThread(
        pi.hProcess, NULL, 0,
        (LPTHREAD_START_ROUTINE)GetProcAddress(GetModuleHandleW(L"kernel32.dll"),
                                               "LoadLibraryW"),
        remoteDll, 0, NULL);
    if (!remoteThread)
        goto inject_failed;
    if (WaitForSingleObject(remoteThread, 15000) != WAIT_OBJECT_0) {
        SetLastError(ERROR_TIMEOUT);
        goto inject_failed;
    }
    if (!GetExitCodeThread(remoteThread, &remoteModule) || !remoteModule) {
        SetLastError(ERROR_DLL_INIT_FAILED);
        goto inject_failed;
    }

    wprintf(L"NetRedirect loaded at 0x%08lX\n", remoteModule);
    wprintf(L"Ragnarok.exe running with NetRedirect.\n");

    if (remoteDll)
        VirtualFreeEx(pi.hProcess, remoteDll, 0, MEM_RELEASE);
    if (remoteThread)
        CloseHandle(remoteThread);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;

inject_failed:
    fail(L"NetRedirect injection");
    TerminateProcess(pi.hProcess, 1);
    if (remoteDll)
        VirtualFreeEx(pi.hProcess, remoteDll, 0, MEM_RELEASE);
    if (remoteThread)
        CloseHandle(remoteThread);
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 1;
}
