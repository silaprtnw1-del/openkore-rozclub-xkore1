#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <windows.h>
#include <iphlpapi.h>
#include <stdio.h>
#include <stdlib.h>

int main(void)
{
    DWORD size = 0;
    PMIB_TCPTABLE_OWNER_PID table;
    DWORD result = GetExtendedTcpTable(NULL, &size, FALSE, AF_INET,
                                       TCP_TABLE_OWNER_PID_ALL, 0);
    if (result != ERROR_INSUFFICIENT_BUFFER) {
        fprintf(stderr, "size query failed: result=%lu size=%lu\n", result, size);
        return 1;
    }
    table = (PMIB_TCPTABLE_OWNER_PID)malloc(size);
    if (!table)
        return 2;
    result = GetExtendedTcpTable(table, &size, FALSE, AF_INET,
                                 TCP_TABLE_OWNER_PID_ALL, 0);
    if (result != NO_ERROR) {
        fprintf(stderr, "table query failed: result=%lu size=%lu\n", result, size);
        return 3;
    }
    for (DWORD i = 0; i < table->dwNumEntries; ++i) {
        MIB_TCPROW_OWNER_PID *row = &table->table[i];
        unsigned short port = ntohs((unsigned short)row->dwLocalPort);
        if (port == 2350)
            printf("state=%lu local_port=%u pid=%lu\n",
                   row->dwState, port, row->dwOwningPid);
    }
    free(table);
    return 0;
}
