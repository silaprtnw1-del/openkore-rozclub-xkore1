/*
 * This DLL is "injected" into the RO client's address space.
 * Once injected, we intercept all network traffic and tee a copy
 * of RO server/client packets to OpenKore while letting d3d9.dll
 * handle the Map Server stream cipher and THAA overlay frames.
 */

#include <stdio.h>
#include "common.h"
#include <string>
#include <string.h>

using namespace std;

MyRecvProc		OriginalRecvProc	= (MyRecvProc) recv;
MySendProc		OriginalSendProc	= (MySendProc) send;
MyRecvFromProc		OriginalRecvFromProc	= (MyRecvFromProc) recvfrom;
MySendToProc		OriginalSendToProc	= (MySendToProc) sendto;
MyConnectProc		OriginalConnectProc	= (MyConnectProc) connect;
MySelectProc		OriginalSelectProc	= (MySelectProc) select;
MyIoctlSocketProc	OriginalIoctlSocketProc	= (MyIoctlSocketProc) ioctlsocket;
MyWSARecvProc		OriginalWSARecvProc	= (MyWSARecvProc) WSARecv;
MyWSARecvFromProc	OriginalWSARecvFromProc	= (MyWSARecvFromProc) WSARecvFrom;
MyWSASendProc		OriginalWSASendProc	= (MyWSASendProc) WSASend;
MyWSASendToProc		OriginalWSASendToProc	= (MyWSASendToProc) WSASendTo;
MyWSAAsyncSelectProc	OriginalWSAAsyncSelectProc = (MyWSAAsyncSelectProc) WSAAsyncSelect;
MyGetProcAddressProc	OriginalGetProcAddressProc = (MyGetProcAddressProc) GetProcAddress;

MyRecvProc		RealRecvProc		= NULL;
MySendProc		RealSendProc		= NULL;
MySelectProc		RealSelectProc		= NULL;
MyConnectProc		RealConnectProc		= NULL;

bool enableDebug = false;


// Connection to the X-Kore server that Kore created
static SOCKET koreClient = INVALID_SOCKET;
static bool koreClientIsAlive = false;
static CRITICAL_SECTION CS_koreClientIsAlive;

static bool dataAvailableFromKore = false;
static bool dataAvailableFromKore2 = false;
static CRITICAL_SECTION CS_dataAvailableFromKore;

static SOCKET roServer = INVALID_SOCKET;
static CRITICAL_SECTION CS_ro;

static CRITICAL_SECTION CS_rosend;
static CRITICAL_SECTION CS_send;
static string roSendBuf("");	// Synthetic packets injected by Kore for the RO client
static string xkoreSendBuf("");	// Tee'd packets to send to the X-Kore server

#define SLEEP_TIME 5


static void
queueToKore (char frameID, const char *data, int len)
{
	if (!data || len <= 0)
		return;

	EnterCriticalSection (&CS_send);
	int offset = 0;
	while (offset < len) {
		int chunk = len - offset;
		if (chunk > 32768)
			chunk = 32768;
		unsigned short sLen = (unsigned short) chunk;
		char hdr[3];
		hdr[0] = frameID;
		memcpy (hdr + 1, &sLen, 2);
		xkoreSendBuf.append (hdr, 3);
		xkoreSendBuf.append (data + offset, chunk);
		offset += chunk;
	}
	LeaveCriticalSection (&CS_send);
}


// Process a packet that the X-Kore server sent us
static void
processPacket (Packet *packet)
{	
	switch (packet->ID) {
	case 'S': // Send a bot-originated packet to the RO server (through d3d9.dll's send hook)
		EnterCriticalSection (&CS_ro);
		if (roServer != INVALID_SOCKET && packet->len > 0)
			OriginalSendProc (roServer, packet->data, packet->len, 0);
		LeaveCriticalSection (&CS_ro);
		break;

	case 'R': // Inject a synthetic packet into the RO client's recv stream
		if (packet->len > 0) {
			EnterCriticalSection (&CS_rosend);
			roSendBuf.append (packet->data, packet->len);
			LeaveCriticalSection (&CS_rosend);
			dataAvailableFromKore2 = true;
		}
		break;

	case 'K': default: // Keep-alive
		break;
	}
}

// Handles the connection between the RO client (this process) and the X-Kore server
// Note that this function is run in a thread and never exits
static DWORD WINAPI
koreConnectionMain (LPVOID)
{
	#define BUF_SIZE 1024 * 32
	#define TIMEOUT 600000
	#define PING_INTERVAL 5000
	#define RECONNECT_INTERVAL 3000

	char buf[BUF_SIZE + 1];
	char pingPacket[3];
	unsigned short pingPacketLength = 0;
	DWORD koreClientTimeout, koreClientPingTimeout, reconnectTimeout;
	string koreClientRecvBuf;

	debug ("Thread started\n");
	koreClientTimeout = GetTickCount ();
	koreClientPingTimeout = GetTickCount ();
	reconnectTimeout = 0;

	memcpy (pingPacket, "K", 1);
	memcpy (pingPacket + 1, &pingPacketLength, 2);

	while (1) {
		MySendProc koreSendFn = RealSendProc ? RealSendProc : OriginalSendProc;
		bool isAlive;
		bool isAliveChanged = false;

		// Attempt to connect to the X-Kore server if necessary
		EnterCriticalSection (&CS_koreClientIsAlive);
		koreClientIsAlive = koreClient != INVALID_SOCKET;
		isAlive = koreClientIsAlive;
		LeaveCriticalSection (&CS_koreClientIsAlive);

		if ((!isAlive || !isConnected (koreClient) || GetTickCount () - koreClientTimeout > TIMEOUT)
		  && GetTickCount () - reconnectTimeout > RECONNECT_INTERVAL) {
			debug ("Connecting to X-Kore server...\n");

			if (koreClient != INVALID_SOCKET)
				closesocket (koreClient);
			koreClient = createSocket (XKORE_SERVER_PORT);

			isAlive = koreClient != INVALID_SOCKET;
			isAliveChanged = true;
			if (!isAlive)
				debug ("Failed\n");
			else
				koreClientTimeout = GetTickCount ();
			reconnectTimeout = GetTickCount ();
		}


		// Receive data from the X-Kore server
		if (isAlive) {
			int ret;

			ret = readSocket (koreClient, buf, BUF_SIZE);
			if (ret == SF_CLOSED) {
				// Connection closed
				debug ("X-Kore server exited\n");
				closesocket (koreClient);
				koreClient = INVALID_SOCKET;
				isAlive = false;
				isAliveChanged = true;

			} else if (ret > 0) {
				// Data available
				Packet *packet;
				int next = 0;

				koreClientRecvBuf.append (buf, ret);
				while ((packet = unpackPacket (koreClientRecvBuf.c_str (), koreClientRecvBuf.size (), next))) {
					processPacket (packet);
					free (packet);
					koreClientRecvBuf.erase (0, next);
				}

				if (dataAvailableFromKore2) {
					EnterCriticalSection (&CS_dataAvailableFromKore);
					dataAvailableFromKore = true;
					LeaveCriticalSection (&CS_dataAvailableFromKore);
					dataAvailableFromKore2 = false;
				}

				// Update timeout
				koreClientTimeout = GetTickCount ();
			}
		}


		// Flush tee'd packets to the X-Kore server using RealSendProc so d3d9.dll ignores koreClient
		EnterCriticalSection (&CS_send);
		if (xkoreSendBuf.size ()) {
			if (isAlive) {
				int sent = koreSendFn (koreClient, (char *) xkoreSendBuf.c_str (), xkoreSendBuf.size (), 0);
				if (sent > 0) {
					xkoreSendBuf.erase (0, sent);
				} else if (sent == SOCKET_ERROR && WSAGetLastError () != WSAEWOULDBLOCK) {
					xkoreSendBuf.erase ();
				}
			} else {
				xkoreSendBuf.erase ();
			}
		}
		LeaveCriticalSection (&CS_send);


		// Ping the X-Kore server to keep the connection alive
		if (isAlive && GetTickCount () - koreClientPingTimeout > PING_INTERVAL) {
			koreSendFn (koreClient, pingPacket, 3, 0);
			koreClientPingTimeout = GetTickCount ();
		}

		if (isAliveChanged) {
			EnterCriticalSection (&CS_koreClientIsAlive);
			koreClientIsAlive = isAlive;
			LeaveCriticalSection (&CS_koreClientIsAlive);
		}
		Sleep (SLEEP_TIME);
	}
}


/*********** Faked functions ************/

int WINAPI
MyWSASend (SOCKET s, LPWSABUF lpBuffers, DWORD dwBufferCount, LPDWORD lpNumberOfBytesSent, DWORD dwFlags, LPWSAOVERLAPPED lpOverlapped, LPWSAOVERLAPPED_COMPLETION_ROUTINE lpCompletionRoutine)
{
	return OriginalWSASendProc(s,lpBuffers,dwBufferCount,lpNumberOfBytesSent,dwFlags,lpOverlapped,lpCompletionRoutine);
}

int WINAPI
MyWSASendTo (SOCKET s, LPWSABUF lpBuffers, DWORD dwBufferCount, LPDWORD lpNumberOfBytesSent, DWORD dwFlags, struct sockaddr* lpTo, int iToLen, LPWSAOVERLAPPED lpOverlapped, LPWSAOVERLAPPED_COMPLETION_ROUTINE lpCompletionRoutine) {
	return OriginalWSASendToProc(s,lpBuffers,dwBufferCount,lpNumberOfBytesSent,dwFlags,lpTo,iToLen,lpOverlapped,lpCompletionRoutine);
}

int WINAPI
MyWSARecv (SOCKET s, LPWSABUF lpBuffers, DWORD dwBufferCount, LPDWORD lpNumberOfBytesRecvd, LPDWORD lpFlags, LPWSAOVERLAPPED lpOverlapped, LPWSAOVERLAPPED_COMPLETION_ROUTINE lpCompletionRoutine)
{
	return OriginalWSARecvProc(s,lpBuffers,dwBufferCount,lpNumberOfBytesRecvd,lpFlags,lpOverlapped,lpCompletionRoutine);
}

int WINAPI
MyWSARecvFrom (SOCKET s, LPWSABUF lpBuffers, DWORD dwBufferCount, LPDWORD lpNumberOfBytesRecvd, LPDWORD lpFlags, struct sockaddr* lpFrom, LPINT lpFromlen, LPWSAOVERLAPPED lpOverlapped, LPWSAOVERLAPPED_COMPLETION_ROUTINE lpCompletionRoutine)
{
	return OriginalWSARecvFromProc(s,lpBuffers,dwBufferCount,lpNumberOfBytesRecvd,lpFlags,lpFrom,lpFromlen,lpOverlapped,lpCompletionRoutine);
}

int WINAPI
MySelect (int nfds, fd_set *readfds, fd_set *writefds, fd_set *exceptfds, const struct timeval *timeout)
{
	SOCKET currentRo = INVALID_SOCKET;
	EnterCriticalSection (&CS_ro);
	currentRo = roServer;
	LeaveCriticalSection (&CS_ro);

	EnterCriticalSection (&CS_rosend);
	bool hasInjected = (roSendBuf.size () > 0);
	LeaveCriticalSection (&CS_rosend);

	if (hasInjected && readfds && currentRo != INVALID_SOCKET && FD_ISSET (currentRo, readfds)) {
		FD_ZERO (readfds);
		FD_SET (currentRo, readfds);
		if (writefds)
			FD_ZERO (writefds);
		if (exceptfds)
			FD_ZERO (exceptfds);
		return 1;
	}

	return OriginalSelectProc(nfds, readfds, writefds, exceptfds, timeout);
}

int WINAPI
MyIoctlSocket (SOCKET s, long cmd, u_long *argp)
{
	int ret = OriginalIoctlSocketProc (s, cmd, argp);
	if (ret == 0 && cmd == (long)FIONREAD && argp) {
		SOCKET currentRo = INVALID_SOCKET;
		EnterCriticalSection (&CS_ro);
		currentRo = roServer;
		LeaveCriticalSection (&CS_ro);

		if (s == currentRo && currentRo != INVALID_SOCKET) {
			EnterCriticalSection (&CS_rosend);
			u_long extra = (u_long) roSendBuf.size ();
			LeaveCriticalSection (&CS_rosend);
			*argp += extra;
		}
	}
	return ret;
}

int WINAPI
MySend (SOCKET s, char* buf, int len, int flags)
{
	if (s == koreClient) {
		MySendProc koreSendFn = RealSendProc ? RealSendProc : OriginalSendProc;
		return koreSendFn (s, buf, len, flags);
	}

	if (len <= 0 || !buf) {
		return OriginalSendProc (s, buf, len, flags);
	}

	// Copy plaintext before calling OriginalSendProc (d3d9.dll's send hook)
	char *plainCopy = (char *) malloc (len);
	if (plainCopy)
		memcpy (plainCopy, buf, len);

	EnterCriticalSection (&CS_ro);
	roServer = s;
	int ret = OriginalSendProc (s, buf, len, flags);
	DWORD lastErr = (ret == SOCKET_ERROR) ? WSAGetLastError () : 0;
	LeaveCriticalSection (&CS_ro);

	if (ret > 0 && plainCopy) {
		bool isAlive;
		EnterCriticalSection (&CS_koreClientIsAlive);
		isAlive = koreClientIsAlive;
		LeaveCriticalSection (&CS_koreClientIsAlive);

		if (isAlive)
			queueToKore ('S', plainCopy, ret);
	}

	if (plainCopy)
		free (plainCopy);

	if (ret == SOCKET_ERROR)
		WSASetLastError (lastErr);

	return ret;
}

int WINAPI
MySendTo (SOCKET s, char* buf, int len, int flags, struct sockaddr* to, int tolen)
{
	return OriginalSendToProc(s,buf,len,flags, to, tolen);
}

int WINAPI
MyRecv (SOCKET s, char* buf, int len, int flags)
{
	if (s == koreClient) {
		MyRecvProc koreRecvFn = RealRecvProc ? RealRecvProc : OriginalRecvProc;
		return koreRecvFn (s, buf, len, flags);
	}

	// If OpenKore explicitly queued synthetic data for the client, deliver it first
	SOCKET currentRo = INVALID_SOCKET;
	EnterCriticalSection (&CS_ro);
	currentRo = roServer;
	LeaveCriticalSection (&CS_ro);

	if (s == currentRo && currentRo != INVALID_SOCKET && len > 0 && buf) {
		EnterCriticalSection (&CS_rosend);
		int roSendBufsize = (int) roSendBuf.size ();
		if (roSendBufsize > 0) {
			int ret = roSendBufsize < len ? roSendBufsize : len;
			memcpy (buf, roSendBuf.c_str (), ret);
			if (!(flags & MSG_PEEK))
				roSendBuf.erase (0, ret);
			LeaveCriticalSection (&CS_rosend);
			return ret;
		}
		LeaveCriticalSection (&CS_rosend);
	}

	// Tee mode: read from OriginalRecvProc (which invokes d3d9.dll's recv hook to
	// decrypt Map Server S2C traffic and strip 0x0cf0 THAA frames), return it
	// immediately to Ragnarok.exe, and tee a copy to OpenKore.
	int ret2 = OriginalRecvProc (s, buf, len, flags);
	if (ret2 > 0 && buf) {
		EnterCriticalSection (&CS_ro);
		roServer = s;
		LeaveCriticalSection (&CS_ro);

		if (!(flags & MSG_PEEK)) {
			bool isAlive;
			EnterCriticalSection (&CS_koreClientIsAlive);
			isAlive = koreClientIsAlive;
			LeaveCriticalSection (&CS_koreClientIsAlive);

			if (isAlive)
				queueToKore ('R', buf, ret2);
		}
	} else if (ret2 == 0 || (ret2 == SOCKET_ERROR && WSAGetLastError () != WSAEWOULDBLOCK)) {
		DWORD lastErr = WSAGetLastError ();
		EnterCriticalSection (&CS_ro);
		if (roServer == s)
			roServer = INVALID_SOCKET;
		LeaveCriticalSection (&CS_ro);
		WSASetLastError (lastErr);
	}

	return ret2;
}

int WINAPI
MyRecvFrom (SOCKET s, char* buf, int len, int flags, struct sockaddr* from, int *fromlen)
{
	return OriginalRecvFromProc(s,buf,len,flags,from,fromlen);
}

int WINAPI
MyConnect (SOCKET s, struct sockaddr* name, int namelen)
{
	if (s != koreClient && name && namelen >= (int) sizeof (sockaddr_in)) {
		const sockaddr_in *sin = (const sockaddr_in *) name;
		if (sin->sin_family == AF_INET && sin->sin_addr.s_addr != inet_addr ("127.0.0.1")) {
			EnterCriticalSection (&CS_ro);
			roServer = s;
			LeaveCriticalSection (&CS_ro);

			EnterCriticalSection (&CS_rosend);
			roSendBuf.erase ();
			LeaveCriticalSection (&CS_rosend);
		}
	}
	return OriginalConnectProc(s, name, namelen);
}

int WINAPI
MyWSAAsyncSelect (SOCKET s, HWND hWnd, unsigned int wMsg, long lEvent)
{
	if (s != koreClient) {
		EnterCriticalSection (&CS_ro);
		roServer = s;
		LeaveCriticalSection (&CS_ro);
	}
	return OriginalWSAAsyncSelectProc(s,hWnd,wMsg,lEvent);
}

FARPROC WINAPI
MyGetProcAddress (HMODULE hModule, LPCSTR lpProcName)
{
	FARPROC ret = OriginalGetProcAddressProc (hModule, lpProcName);
	HMODULE WS2_32 = GetModuleHandleA ("WS2_32.DLL");
	if (hModule == WS2_32 && HIWORD (lpProcName) != 0) {
		if (stricmp (lpProcName, "WSASend") == 0) {
			OriginalWSASendProc = (MyWSASendProc) ret;
			ret = (FARPROC) MyWSASend;

		} else if (stricmp (lpProcName, "WSASendTo") == 0) {
			OriginalWSASendToProc = (MyWSASendToProc) ret;
			ret = (FARPROC) MyWSASendTo;

		} else if (stricmp (lpProcName, "WSARecv") == 0) {
			OriginalWSARecvProc = (MyWSARecvProc) ret;
			ret = (FARPROC) MyWSARecv;

		} else if (stricmp (lpProcName, "WSARecvFrom") == 0) {
			OriginalWSARecvFromProc = (MyWSARecvFromProc) ret;
			ret = (FARPROC) MyWSARecvFrom;

		} else if (stricmp (lpProcName, "send") == 0) {
			OriginalSendProc = (MySendProc) ret;
			ret = (FARPROC) MySend;

		} else if (stricmp (lpProcName, "sendto") == 0) {
			OriginalSendToProc = (MySendToProc) ret;
			ret = (FARPROC) MySendTo;

		} else if (stricmp (lpProcName, "recv") == 0) {
			OriginalRecvProc = (MyRecvProc) ret;
			ret = (FARPROC) MyRecv;

		} else if (stricmp (lpProcName, "recvfrom") == 0) {
			OriginalRecvFromProc = (MyRecvFromProc) ret;
			ret = (FARPROC) MyRecvFrom;

		} else if (stricmp (lpProcName, "connect") == 0) {
			OriginalConnectProc = (MyConnectProc) ret;
			ret = (FARPROC) MyConnect;

		} else if (stricmp (lpProcName, "select") == 0) {
			OriginalSelectProc = (MySelectProc) ret;
			ret = (FARPROC) MySelect;

		} else if (stricmp (lpProcName, "ioctlsocket") == 0) {
			OriginalIoctlSocketProc = (MyIoctlSocketProc) ret;
			ret = (FARPROC) MyIoctlSocket;

		} else if (stricmp (lpProcName, "WSAAsyncSelect") == 0) {
			OriginalWSAAsyncSelectProc = (MyWSAAsyncSelectProc) ret;
			ret = (FARPROC) MyWSAAsyncSelect;
		}
	}
 	return ret;
}

/************************************************/


static void
DoHookProcs ()
{
	RealSendProc    = (MySendProc)    GetUnpatchedWinsockProc ((PSTR)"send");
	RealRecvProc    = (MyRecvProc)    GetUnpatchedWinsockProc ((PSTR)"recv");
	RealSelectProc  = (MySelectProc)  GetUnpatchedWinsockProc ((PSTR)"select");
	RealConnectProc = (MyConnectProc) GetUnpatchedWinsockProc ((PSTR)"connect");

	OriginalWSASendProc = (MyWSASendProc)
			HookImportedFunction( GetModuleHandle(0), (PSTR)"WS2_32.DLL", (PSTR)"WSASend", (PROC)MyWSASend);

	OriginalWSASendToProc = (MyWSASendToProc)
			HookImportedFunction( GetModuleHandle(0), (PSTR)"WS2_32.DLL", (PSTR)"WSASendTo", (PROC)MyWSASendTo);

	OriginalWSARecvProc = (MyWSARecvProc)
			HookImportedFunction( GetModuleHandle(0), (PSTR)"WS2_32.DLL", (PSTR)"WSARecv", (PROC)MyWSARecv);

	OriginalWSARecvFromProc = (MyWSARecvFromProc)
			HookImportedFunction( GetModuleHandle(0), (PSTR)"WS2_32.DLL", (PSTR)"WSARecvFrom", (PROC)MyWSARecvFrom);

	OriginalSendProc = (MySendProc)
			HookImportedFunction( GetModuleHandle(0), (PSTR)"WS2_32.DLL", (PSTR)"send", (PROC)MySend);

	OriginalSendToProc = (MySendToProc)
			HookImportedFunction( GetModuleHandle(0), (PSTR)"WS2_32.DLL", (PSTR)"sendto", (PROC)MySendTo);

	OriginalRecvProc = (MyRecvProc)
			HookImportedFunction( GetModuleHandle(0), (PSTR)"WS2_32.DLL", (PSTR)"recv", (PROC)MyRecv);

	OriginalRecvFromProc = (MyRecvFromProc)
			HookImportedFunction( GetModuleHandle(0), (PSTR)"WS2_32.DLL", (PSTR)"recvfrom", (PROC)MyRecvFrom);

	OriginalConnectProc = (MyConnectProc)
			HookImportedFunction( GetModuleHandle(0), (PSTR)"WS2_32.DLL", (PSTR)"connect", (PROC)MyConnect);

	OriginalSelectProc = (MySelectProc)
			HookImportedFunction( GetModuleHandle(0), (PSTR)"WS2_32.DLL", (PSTR)"select", (PROC)MySelect);

	OriginalIoctlSocketProc = (MyIoctlSocketProc)
			HookImportedFunction( GetModuleHandle(0), (PSTR)"WS2_32.DLL", (PSTR)"ioctlsocket", (PROC)MyIoctlSocket);

	OriginalWSAAsyncSelectProc = (MyWSAAsyncSelectProc)
			HookImportedFunction( GetModuleHandle(0), (PSTR)"WS2_32.DLL", (PSTR)"WSAAsyncSelect", (PROC)MyWSAAsyncSelect);

	OriginalGetProcAddressProc = (MyGetProcAddressProc)
			HookImportedFunction( GetModuleHandle(0), (PSTR)"KERNEL32.DLL", (PSTR)"GetProcAddress", (PROC)MyGetProcAddress);
}

static void
init ()
{
	WSAData WSAData;
	ULONG threadID;

	WSAStartup (MAKEWORD (2,2),&WSAData);
	InitializeCriticalSection (&CS_koreClientIsAlive);
	InitializeCriticalSection (&CS_dataAvailableFromKore);
	InitializeCriticalSection (&CS_ro);
	InitializeCriticalSection (&CS_send);
	InitializeCriticalSection (&CS_rosend);
	debugInit ();

	debug ("Hooking functions...\n");
	DoHookProcs ();
	debug ("Creating thread...\n");
	CreateThread (0, 0, koreConnectionMain, 0, 0, &threadID);
	debug ("Thread created\n");
}


/********* DLL injection support for Win9x *********/

static int isNT = 0;
static int started = 0;
static HINSTANCE hDll = 0;
static HHOOK hookID = 0;

static DWORD WINAPI
start (LPVOID)
{
	init ();
	return 0;
}

// This function is called when we're injected into another process
static LRESULT WINAPI
hookProc (int code, WPARAM wParam, LPARAM lParam)
{
	if (!started) {
		char lib[MAX_PATH];
		ULONG threadID;

		started = 1;
		GetModuleFileName (hDll, lib, MAX_PATH);
		if (LoadLibrary (lib))
			UnhookWindowsHookEx (hookID);

		CreateThread (NULL, 0, start, NULL, 0, &threadID);
	}
	return CallNextHookEx (hookID, code, wParam, lParam);
}

// Inject this DLL into the process that owns window hwnd
extern "C" int WINAPI __declspec(dllexport)
injectSelf (HWND hwnd)
{
	int idHook;

	if (isNT)
		idHook = WH_CALLWNDPROC;
	else
		idHook = WH_GETMESSAGE;

	hookID = SetWindowsHookEx (idHook, (HOOKPROC) hookProc, hDll,
		GetWindowThreadProcessId (hwnd, NULL));
	if (hookID == NULL)
		return 0;

	SendMessage (hwnd, WM_USER + 10, 0, 1);
	return 1;
}

/***************************************************/


extern "C" BOOL APIENTRY
DllMain (HINSTANCE hInstance, DWORD dwReason, LPVOID _Reserved)
{
	switch (dwReason) {
	case DLL_PROCESS_ATTACH:
		hDll = hInstance;

		HKEY key;
		DWORD type, size;
		BYTE val[1024];

		size = sizeof (val) - 1;
		val[0] = '\0';
		if (RegOpenKey (HKEY_CURRENT_USER, "Software\\Kore", &key) == ERROR_SUCCESS) {
			RegQueryValueEx (key, "DebugNetRedirect", NULL, &type, val, &size);
			RegCloseKey (key);
		}
		enableDebug = val[0] == '1';

		#ifndef TESTING_INJECT9x
		OSVERSIONINFO version;

		version.dwOSVersionInfoSize = sizeof (OSVERSIONINFO);
		GetVersionEx (&version);
		isNT = version.dwPlatformId == VER_PLATFORM_WIN32_NT;

		if (isNT)
			init ();
		#endif
		break;

	default:
		break;
	}

	return true;
}
