#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include <stdio.h>

int main(int argc, char **argv)
{
    HMODULE module;

    if (argc != 2) {
        fprintf(stderr, "usage: netredirect_smoke_host.exe NetRedirect.dll\n");
        return 2;
    }
    module = LoadLibraryA(argv[1]);
    if (!module) {
        fprintf(stderr, "LoadLibrary failed: %lu\n", GetLastError());
        return 7;
    }
    printf("NetRedirect loaded; waiting for connection smoke test.\n");
    fflush(stdout);
    Sleep(5000);
    return 0;
}
