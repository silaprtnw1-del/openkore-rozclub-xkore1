#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <stdarg.h>
#include "common.h"


/* Creates a packet data structure.
 * Returns NULL if data is not a full packet, or a Packet structure.
 * next is the offset of the next packet, in case data contains more than one packet.
 */
Packet *
unpackPacket (const char *data, int len, int &next)
{
	Packet *packet;

	if (len < 3)
		return NULL;

	packet = (Packet *) calloc (sizeof (Packet), 1);
	packet->ID = (unsigned char) data[0];
	memcpy (&(packet->len), data + 1, 2);
	if (len < packet->len + 3) {
		free (packet);
		return NULL;
	}

	if (packet->len > 0)
		packet->data = (char *) data + 3;
	next = packet->len + 3;
	return packet;
}


PROC
GetUnpatchedWinsockProc (PSTR FunctionName)
{
	HMODULE hWs2 = GetModuleHandleA ("WS2_32.DLL");
	if (!hWs2)
		hWs2 = LoadLibraryA ("WS2_32.DLL");
	if (!hWs2)
		return NULL;

	BYTE *p = (BYTE *) (OriginalGetProcAddressProc
		? OriginalGetProcAddressProc (hWs2, FunctionName)
		: GetProcAddress (hWs2, FunctionName));
	if (!p)
		return NULL;

	/* If d3d9.dll installed a Windows hotpatch short-jump (EB F9 -> jmp -5)
	 * at the function entry point in ws2_32.dll, advance 2 bytes to the real
	 * post-prologue body so internal XKore loopback traffic does not enter
	 * d3d9.dll's packet hooks. */
	if (p[0] == 0xEB && p[1] == 0xF9)
		return (PROC) (p + 2);

	return (PROC) p;
}


SOCKET
createSocket (int port)
{
	sockaddr_in addr;
	SOCKET sock;
	DWORD arg = 1;
	MyConnectProc connectFn = RealConnectProc ? RealConnectProc : OriginalConnectProc;

	sock = socket (AF_INET, SOCK_STREAM, 0);
	if (sock == INVALID_SOCKET)
		return INVALID_SOCKET;

	addr.sin_family = AF_INET;
	addr.sin_port = htons (port);
	addr.sin_addr.s_addr = inet_addr ("127.0.0.1");
	/* This is always a loopback connection. Complete it in blocking mode,
	 * then switch to non-blocking I/O. */
	if (connectFn (sock, (struct sockaddr *) &addr,
			sizeof (sockaddr_in)) == SOCKET_ERROR) {
		closesocket (sock);
		return INVALID_SOCKET;
	}
	ioctlsocket (sock, FIONBIO, &arg);

	return sock;
}

// Checks whether a socket is still connected
bool
isConnected (SOCKET s)
{
	fd_set fds;
	long count;
	timeval tv;
	MySelectProc selectFn = RealSelectProc ? RealSelectProc : OriginalSelectProc;

	tv.tv_sec = 0;
	tv.tv_usec = 1;
	FD_ZERO (&fds);
	FD_SET (s, &fds);
	count = selectFn (1, NULL, &fds, NULL, &tv);
	return (bool) count;
}

// Checks whether there's data available from a socket
bool
dataWaiting (SOCKET s)
{
	fd_set fds;
	long count;
	timeval tv;
	MySelectProc selectFn = RealSelectProc ? RealSelectProc : OriginalSelectProc;

	tv.tv_sec = 0;
	tv.tv_usec = 1;
	FD_ZERO (&fds);
	FD_SET (s, &fds);
	count = selectFn (1, &fds, NULL, NULL, &tv);
	return (bool) count;
}

int
readSocket (SOCKET s, char *buf, int len)
{
	MyRecvProc recvFn = RealRecvProc ? RealRecvProc : OriginalRecvProc;
	int ret = recvFn (s, buf, len, 0);

	if (ret == 0)
		return SF_CLOSED;
	else if (ret > 0)
		return ret;
	else if (ret == SOCKET_ERROR) {
		if (WSAGetLastError () == WSAEWOULDBLOCK)
			return SF_NODATA;
		else
			return SF_CLOSED;
	} else
		return SF_CLOSED;
}

// Replace an imported function in hModule's IAT, matching either by OriginalFirstThunk
// import name (so slots already hooked by d3d9.dll are still found and chained) or by
// current FirstThunk address.
PROC
HookImportedFunction (HMODULE hModule,		// Module to intercept calls from
			PSTR FunctionModule,	// The dll file that contains the function you want to hook
			PSTR FunctionName,	// The function that you want to hook
			PROC pfnNewProc)	// New function, this gets called instead
{
	#define MakePtr( cast, ptr, addValue ) (cast)( (DWORD)(ptr)+(DWORD)(addValue))
	PROC pfnOriginalProc;
	IMAGE_DOS_HEADER *pDosHeader;
	IMAGE_NT_HEADERS *pNTHeader;
	IMAGE_IMPORT_DESCRIPTOR *pImportDesc;

	if (IsBadCodePtr (pfnNewProc)) return NULL;
	if (OriginalGetProcAddressProc) {
		pfnOriginalProc = OriginalGetProcAddressProc(GetModuleHandle(FunctionModule), FunctionName);
	} else {
		pfnOriginalProc = GetProcAddress(GetModuleHandle(FunctionModule), FunctionName);
	}
	if(!pfnOriginalProc) return NULL;

	pDosHeader = (PIMAGE_DOS_HEADER)hModule;

	if ( IsBadReadPtr(pDosHeader, sizeof(IMAGE_DOS_HEADER)) )
		return NULL;
	if ( pDosHeader->e_magic != IMAGE_DOS_SIGNATURE )
		return NULL;

	pNTHeader = MakePtr(PIMAGE_NT_HEADERS, pDosHeader, pDosHeader->e_lfanew);

	if ( IsBadReadPtr(pNTHeader, sizeof(IMAGE_NT_HEADERS)) )
		return NULL;

	if ( pNTHeader->Signature != IMAGE_NT_SIGNATURE )
		return NULL;

	DWORD importRva = pNTHeader->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
	if ( !importRva )
		return pfnOriginalProc;

	pImportDesc = MakePtr(PIMAGE_IMPORT_DESCRIPTOR, pDosHeader, importRva);
	if ( pImportDesc == (PIMAGE_IMPORT_DESCRIPTOR)pNTHeader )
		return NULL;

	PROC pfnChainedOriginal = pfnOriginalProc;

	for ( ; pImportDesc->Name; pImportDesc++ ) {
		PSTR pszModName = MakePtr(PSTR, pDosHeader, pImportDesc->Name);
		if ( stricmp(pszModName, FunctionModule) != 0 )
			continue;

		PIMAGE_THUNK_DATA pThunk = MakePtr(PIMAGE_THUNK_DATA, pDosHeader, pImportDesc->FirstThunk);
		PIMAGE_THUNK_DATA pOrigThunk = pImportDesc->OriginalFirstThunk
			? MakePtr(PIMAGE_THUNK_DATA, pDosHeader, pImportDesc->OriginalFirstThunk)
			: NULL;

		for ( ; pThunk->u1.Function; pThunk++, (pOrigThunk ? pOrigThunk++ : NULL) ) {
			bool matched = false;

			if ( (DWORD)pThunk->u1.Function == (DWORD)pfnOriginalProc ) {
				matched = true;
			} else if ( pOrigThunk && pOrigThunk->u1.AddressOfData && !(pOrigThunk->u1.Ordinal & IMAGE_ORDINAL_FLAG32) ) {
				PIMAGE_IMPORT_BY_NAME pByName = MakePtr(PIMAGE_IMPORT_BY_NAME, pDosHeader, pOrigThunk->u1.AddressOfData);
				if ( !IsBadReadPtr(pByName, sizeof(WORD) + 1) && stricmp((char *)pByName->Name, FunctionName) == 0 ) {
					matched = true;
				}
			}

			if ( matched ) {
				PROC currentTarget = (PROC)pThunk->u1.Function;
				if ( currentTarget && currentTarget != pfnNewProc )
					pfnChainedOriginal = currentTarget;

				MEMORY_BASIC_INFORMATION mbi_thunk;
				VirtualQuery(pThunk, &mbi_thunk, sizeof(MEMORY_BASIC_INFORMATION));
				if (VirtualProtect(mbi_thunk.BaseAddress, mbi_thunk.RegionSize, PAGE_READWRITE, &mbi_thunk.Protect)) {
					DWORD *pTemp = (DWORD *)&pThunk->u1.Function;
					*pTemp = (DWORD)pfnNewProc;
					DWORD dummy;
					VirtualProtect(mbi_thunk.BaseAddress, mbi_thunk.RegionSize, mbi_thunk.Protect, &dummy);
				}
			}
		}
	}

	return pfnChainedOriginal;
}


void
debugInit ()
{
	if (enableDebug)
		AllocConsole ();
}

void
debug (const char *format, ...)
{
	if (enableDebug) {
		va_list ap;
		char msg[1024];

		va_start (ap, format);
		vsprintf (msg, format, ap);
		va_end (ap);
		WriteConsole (GetStdHandle (STD_OUTPUT_HANDLE), msg, strlen (msg), NULL, NULL);
	}
}
