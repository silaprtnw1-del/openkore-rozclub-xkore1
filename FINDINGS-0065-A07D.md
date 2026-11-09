# ROZCLUB XKore 1 — the `0065 → A07D → 006C` failure, explained and tested

Scope: diagnosis of OpenKore's char-server login failure on ROZCLUB
(`serverType kRO_RagexeRE_2021_11_03`, XKore 1), from the evidence already in
this profile. No live service was contacted; no client protection was touched.

## TL;DR

It is **not obfuscation, not a wrong packetver, and not a packet-length table
problem.** It is a **stale-session double-login bug**: the client's CH_ENTER
(`0065`) carried the session IDs of its *first* login while the login server
had already advanced to a *second* login's IDs. The char server replied
`006C` HC_REFUSE_ENTER, and the 4-byte account ID that precedes that reply was
misread by OpenKore as the opcode `A07D`.

## Evidence (logs/console.txt, 2026-11-02 14:32 run)

Captured bytes, reframed byte-for-byte:

| Packet | Raw hex | Meaning |
|---|---|---|
| client `0064` | `6400 13000000 Sila03044600… Sila25461!…` | account login |
| server `0AC4` #1 (14:31:56) | `c40a e000 2a30c1fe 7da01e00 bbe0d17b …` | accept: loginID1=`2a30c1fe`, accountID=2007165, loginID2=`bbe0d17b` |
| server `0AC4` #2 (14:32:23) | `c40a e000 3f76b4f9 7da01e00 91901cd2 …` | **re-accept: loginID1=`3f76b4f9`, loginID2=`91901cd2`** |
| client `0065` (14:32:24) | `6500 7da01e00 2a30c1fe bbe0d17b 0000 01` | CH_ENTER with **login #1's** IDs |
| server reply (14:32:24) | `7da01e00 6c00 00` | **[accountID 2007165][opcode `006C`][errcode 0]** |

Two independent facts come straight out of these bytes:

1. **The `A07D` is a framing artifact, not a packet.** The server reply's first
   four bytes `7d a0 1e 00` are exactly the account ID the client just sent
   (`0x001EA07D` = 2007165) — plaintext, unencrypted. OpenKore read the low two
   bytes (`7d a0`) as a little-endian switch and printed `A07D`. The real
   message is the classic char-server pair **`[naked accountID][006C refuse]`**.
   This rules out packet-ID obfuscation on this exchange.

2. **The refusal cause is stale session IDs.** The client's CH_ENTER loginID1/2
   = `2a30c1fe` / `bbe0d17b` = **login #1**. The server's live session (from
   `0AC4` #2) expected `3f76b4f9` / `91901cd2` = **login #2**. Mismatched
   session IDs → `006C` errcode 0. The parser confusion did not cause the
   refusal; the server genuinely rejected the mismatch.

`$Globals::accountID` was set correctly (the log prints
`Account ID: 2007165  7D A0 1E 00`), so the naked-account-ID consumption path
in `Network::MessageTokenizer` could not engage only because, in the pre-fix
build that ran, nothing rewrote the stale CH_ENTER IDs first.

## Why the existing fix did not run (deployment finding)

`src/Network/XKore.pm` already contains a CH_ENTER rewrite that replaces the
client's loginID1/2 with the newest `$Globals::sessionID` / `sessionID2`. It did
not run in the captured failure for one plain reason: **it did not exist yet.**
Both `C:\Users\silap\openkore\src\Network\XKore.pm` and this profile's
`runtime\Network\XKore.pm` were last modified **14:49** on 2026-11-02 —
**16 minutes after** the last captured run (console ends 14:33; that run even
logged a `login_error_game_login_server` debug line that exists in neither
current copy). The fix postdates every capture, so it has never been exercised
against the server.

### Module-loading paths (verified 2026-11-05)

An earlier draft of this note worried that the launcher's
`PERL5LIB` (`runtime;…;src;…`) let `runtime\Network\XKore.pm` shadow the
canonical `src` copy. **That is not what happens.** `openkore.pl` runs, at
compile time, after `PERL5LIB` is applied:

```
use FindBin qw($RealBin);   # $RealBin = C:\Users\silap\openkore
use lib "$RealBin";
use lib "$RealBin/src";
use lib "$RealBin/src/deps";
```

`use lib` **prepends**, so `C:\Users\silap\openkore\src` lands ahead of the
`runtime` entry. Resolving `@INC` with the launcher's exact `PERL5LIB`:

```
Network/XKore.pm            -> C:/Users/silap/openkore/src/Network/XKore.pm
Network/XKoreSessionFix.pm  -> C:/Users/silap/openkore/src/Network/XKoreSessionFix.pm
effective @INC: [0] .../openkore/src/deps  [1] .../openkore/src  [2] .../openkore
               [3] <profile>/runtime  [4] ...src  [5] ...src/deps  [6] Strawberry
```

So **`src` wins; `runtime\Network\XKore.pm` is never loaded** (dead copy), and
the new `XKoreSessionFix.pm` in `src` is reachable. The fix and the helper will
load. No `PERL5LIB` reorder or `runtime` sync is required.

A load-time diagnostic now confirms this at runtime. `XKore->new()` prints
(when `XKore_transitionTrace 1`, which this profile sets):

```
[XKore] loaded C:/Users/silap/openkore/src/Network/XKore.pm (XKoreSessionFix available)
```

## Change made (this session)

Verification-only refactor; behaviour of the rewrite is unchanged.

| File | Change |
|---|---|
| `src/Network/XKoreSessionFix.pm` | **New.** Pure, dependency-free `rewrite_chenter(\$msg, $sessionID, $sessionID2)` — the exact CH_ENTER rewrite, extracted so it is unit-testable without XSTools/sockets/Globals. |
| `src/Network/XKore.pm` | The inline rewrite now calls `Network::XKoreSessionFix::rewrite_chenter`. One `use` line added. No behaviour change. |
| `src/Network/test/xkore_chenter_rewrite.t` | **New.** 14 assertions built from the captured bytes. |

Result (WSL perl, offline): **14/14 pass.** Fed the exact refused CH_ENTER and
`0AC4` #2's session IDs, the helper rewrites
`65007da01e00 2a30c1fe bbe0d17b 000001` →
`65007da01e00 3f76b4f9 91901cd2 000001` — i.e. the IDs the server expected —
while leaving the accountID and sex fields untouched. Guards confirm it ignores
non-`0065`, truncated, and missing-ID inputs.

`perl -c` on the refactored `XKore.pm` is clean.

## Status

- **Root cause: established** from existing evidence (byte-level).
- **Classification: established** — stale-session double login; *not* obfuscation,
  *not* packetver, *not* a length-table/framing defect.
- **Fix logic: verified offline** against the real failing bytes (14/14).
- **Fix end-to-end: UNVERIFIED** — no run has happened since the fix was added.

## Blocked / out of scope (needs you, or a decision)

1. **One live login to confirm end-to-end.** My boundary: I do not drive the
   live client or server to probe its controls. Starting one XKore 1 login and
   watching the log is yours to run. Module loading is already verified (above),
   so no pre-step is needed; on startup expect
   `[XKore] loaded …/src/Network/XKore.pm (XKoreSessionFix available)`, and on
   the double-login expect `[XKore fix] CH_ENTER session IDs … -> …` followed by
   the character list loading.
2. **Why the client double-logs-in through XKore 1 at all.** The second `0AC4`
   is what makes the first login's IDs stale. That reconnect behaviour is a
   separate XKore-1 question; the rewrite masks its effect but does not remove
   the cause.
3. **Residual race.** The rewrite reads `$Globals::sessionID`, set when
   `account_server_info` parses `0AC4`. In the capture the second `0AC4` was
   parsed ~1 s before the `0065`, so the globals were current. A tighter
   double-login could send `0065` before the second `0AC4` is parsed; a fully
   robust version would latch the newest IDs from the raw `0AC4` bytes inside
   `XKore.pm`. Noted, not yet needed by the evidence.
4. **If the server still refuses after the IDs are corrected,** that is a
   server-side decision (session policy, anti-cheat), not an OpenKore bug. I
   will diagnose it from your server-side config/logs, not by defeating a client
   control.

---

# Stage 2 (2026-11-05 19:20 run): login now succeeds; char list mis-parsed

The CH_ENTER fix is loaded (`[XKore] loaded src/Network/XKore.pm
(XKoreSessionFix available)`), and this run got **past** `006C` into the char
list: `082D` + `006B`, then "Received characters from Character Server", state
2 -> 3. But slot 0 showed an empty name and level 0/0 while the raw payload
plainly contained `potato7` and `pay_dc01.gat`.

## Decoded response (257 bytes, server -> client, labelled `A07D` len 257)

| Region | Bytes | Content |
|---|---|---|
| naked accountID | `[0:4]` | `7d a0 1e 00` = 2007165 (same misread-as-`A07D` prefix as before) |
| `082D` HC_ACCEPT_ENTER2 | `[4:33]`, len 29 | slot counts `0f 00 00 0f 0f` (15 normal / 15 premium / 15 billing) |
| `006B` received_characters | `[33:235]`, len 202 | `'v C3 x20 a*'` -> charInfo starts 27 B in = abs byte 60 |
| char block (slot 0) | `[60:235]` | **175 bytes, one block** |
| tail | `[235:257]`, 22 B | `a0 09 …` — a trailing packet (opcode `09A0`?) ending in the accountID again; not yet classified |

## Why the name and level were wrong — CONFIRMED

`received_characters()` slices each block by `charBlockSize` and unpacks it with
the template `received_characters_unpackString` selects from that same number.
The profile set `charBlockSize 155`; the server's block is **175**. Unpacking
the captured 175-byte block both ways:

| charBlockSize | name | base lv | last_map |
|---|---|---|---|
| **155** (old config) | `''` | **0** | `''` |
| **175** (actual) | `potato7` | **7** (job 3, jobID 6 = Thief) | `pay_dc01.gat` |
| 247 (serverType "official") | potato7 | 7 | `''` (Z96 overruns) |

The 155 row reproduces the reported symptom exactly. Proven offline in
`src/Network/test/rozclub_char_block.t` (9/9), using the stock 155 and 175
templates from `Network::Receive`.

## Fix applied

`tables/servers.txt` (this profile), `[ROZCLUB]`: `charBlockSize 155` ->
`charBlockSize 175`. This selects the 175-byte block for both the stride and
the unpack template. **Config only; no parser code, injection, or protection
touched. UNVERIFIED live** (no run since the change).

## Confirmed vs hypothesis

- **CONFIRMED:** char block is 175 bytes; `charBlockSize 155` caused the empty
  name / level 0 (byte-level unpack). The `A07D` label is again just the naked
  4-byte accountID prefix, not a real opcode. Login itself now succeeds
  (`006B`, not `006C`).
- **CONFIRMED (negative):** the `[XKore fix]` rewrite message is absent because
  this was a single login (`0064 -> 083E -> 0065`, no second `0AC4`); the client
  sent current IDs, so the rewrite had nothing to change. Its code path is
  loaded; whether `rewrite_chenter` was entered on a no-op is not observable
  from the log, and the successful `006B` shows the IDs were accepted either way.
- **HYPOTHESIS (unproven):** the real client staying at "Waiting for Connection"
  after OpenKore parsed the char list. Likely the client awaits the char-select
  round trip through the XKore relay, or the 22-byte trailing `09A0`-ish packet /
  relay sequencing. This sits in the live-client injection/redirection layer,
  which was deliberately not touched or tested. Needs one live run to observe,
  and is not established as an OpenKore parsing bug.

## Most likely remaining root cause

For the **mis-displayed character**: `charBlockSize 155` vs the server's 175-byte
block — now fixed in config, pending a live confirmation. For the **client
still waiting**: unproven; it is a relay/char-select interaction, not a parsing
defect, and is out of the authorized diagnostic scope until observed live.

---

# Stage 3 (2026-11-05 19:36 run): char list OK, client still "Connection Failed"

Read-only source + log analysis only. No injection/redirection/anti-cheat
mechanism was touched; the client was not launched by me.

## Confirmed facts (observed)

1. **The CH_ENTER rewrite now fires on a real double login.** Log 19:37:05.71:
   `[XKore fix] CH_ENTER session IDs 57e8b2e4...2ecfa6a5 -> 9215e533...54e8eb86`.
   The client's `0065` carried login #1's IDs; OpenKore rewrote them to login
   #2's. The char server then accepted (no `006C`).
2. **Char list parses correctly** (charBlockSize 175): `Slot 0: potato7
   (Thief, Boy, level 7/3, pay_dc01)`; `state 2 -> 3`; "Received characters".
3. **The server's char-server reply is complete and fully framable.** Decoded
   offline: `[accountID 4] 082D(29) 006B(202) 09A0(6) 020D(4) 08B9(12)` = 257
   bytes. Every opcode is in this serverType's `recvpackets.txt`
   (`09A0`=6, `020D`=-1→4, `08B9`=12, `006B`=-1, `082D`=-1). `08B9` is the
   pincode-state packet → log "PIN code is correct."
4. **OpenKore's XKore-1 relay forwards these bytes unaltered.** Path
   (`functions.pl:940`): `$net->clientSend($_) for $packetParser->process(...)`.
   In `PacketParser::process`, `ACCOUNT_ID` tokens are pushed to the result
   (the naked 4-byte account-ID prefix is forwarded, not swallowed), and
   `Network::Receive` defines no `willMangle`/`mangle`, so every char-server
   packet is forwarded as its original `RAW_MSG`. There is no OpenKore-side
   byte mutation of the char list on the way to the client.
5. **OpenKore logs no disconnect, no timeout, no client `0066` (char-select),
   and no further packets after the char list.** The session simply halts at
   state 3 under `--ai=manual` (which does not auto-select a character).
6. **An earlier run shows an OpenKore↔server login-subprotocol mismatch.** Log
   19:20:18: server sent `083E` (26 bytes); OpenKore's `083E = login_error`
   handler logged "Password Error for account []", yet the session continued to
   the char list. `083E` on this server is not behaving as OpenKore's
   `login_error (V Z20)` model expects.
7. **Every session performs a double login** (two `0064 -> 0AC4` cycles) and the
   server's server-list line reports **"Users 2"** for the account.

## Answers to the four questions

1. **Was the char list delivered to the client, or only parsed?** *Not
   determinable from these logs.* The logs are OpenKore-side only. What is
   proven is that OpenKore *received and would forward* the full, unmangled
   char-server response (facts 3-4). Whether NetRedirect actually delivered
   those bytes to the client socket is **not observable** without a client-side
   / loopback capture of this run.
2. **Are client and proxy session states consistent?** Partially. After the
   rewrite the *session IDs* match (fact 1), which is why the char server
   accepted. But the **double login + "Users 2"** (fact 7) show the account
   holds two concurrent sessions — the client/proxy opened a second login while
   the first was still counted. That is a session-multiplicity inconsistency,
   not a session-ID one.
3. **Do the logs show a disconnect, timeout, client error, or extra server
   response?** No disconnect and no timeout are logged by OpenKore (fact 5).
   The only "error" is the misclassified `083E` "Password Error" (fact 6). The
   extra server response is the post-charlist trailer `09A0/020D/08B9`
   (fact 3), which is benign and framable. The client's own "Connection Failed"
   is **not** recorded in OpenKore's log — it is a client-side event OpenKore
   did not observe.
4. **What distinguishes relay vs protocol vs integrity?**
   - *Relay problem* would require the client to not receive, or receive
     corrupted/truncated, char-server bytes. Facts 3-4 show OpenKore's parser
     and forward path are byte-faithful and nothing is unframable, so a relay
     defect would have to live **below** OpenKore (NetRedirect delivery or the
     map-server redirect), which these logs cannot see.
   - *Protocol incompatibility* is positively evidenced only at the login step
     (`083E` misread, fact 6); no char-stage packet is mis-framed or mangled.
   - *Client-integrity rejection* is consistent with the whole picture — a
     fully successful negotiation that the client nonetheless refuses — plus an
     injected in-process overlay (`d3d9.dll`) and the duplicate-session pattern.
     It is **not proven**; "Connection Failed" is a generic client message.

## Earliest divergence

- **Earliest OpenKore-vs-server protocol divergence (confirmed):** the `083E`
  packet during the login handshake (state 2), read as `login_error "Password
  Error"` on a session that then succeeded. OpenKore's login-subprotocol model
  does not match ROZCLUB here. This precedes the char server.
- **Earliest client behavioural divergence (observed effect, cause
  undetermined):** after the char list at state 3, the client does not proceed
  to char-select (`0066`) and instead reports "Connection Failed". OpenKore's
  side of the flow is clean up to and including the forwarded char list; the
  divergence is at or after the hand-off of that list to the client, which the
  OpenKore-side logs do not cover.

## The one piece of evidence that would decide it (not collected)

A **read-only loopback / client-side packet capture of this post-fix run**,
correlated with the "Connection Failed" moment, would separate the hypotheses:
- client received `[accountID]082D 006B 09A0 020D 08B9` intact, then itself sent
  FIN/RST or went idle → **client-integrity rejection**;
- client received a truncated/absent char list → **relay/transport (NetRedirect)
  problem**;
- client received it, sent `0066`, got `0071/0AC5`, then failed connecting to
  the map-server IP → **map-server redirect / protocol** problem.

Collecting it requires launching the live client, which is outside this task's
scope (no driving the client, no touching injection/redirection/anti-cheat), so
it is left for you to run.

---

# Stage 4 (reassessment with corrected user sequence + Windows crash evidence)

Read-only (Event Log, WER store, existing OpenKore logs). No injection /
redirection / anti-cheat touched; client not launched by me. Corrects the
Stage-3 "double login = proxy churn" reading.

## Corrected reproduction (from the user)

1. First login: client shows "Connecting to server" a long time, then fails.
2. User manually retries.
3. Retry succeeds → server-selection screen.
4. After selecting the server, client hangs on "Connecting to server".
5. OpenKore parses the character list; Ragnarok.exe never shows char-select.
6. Ragnarok.exe eventually exits.

The two `0064` logins are therefore **user-initiated (fail + manual retry)**,
not an automatic client/proxy reconnect. The Stage-3 "double login / Users 2"
churn framing is withdrawn.

## Timeline correlation (19:36 OpenKore run)

| Time | Event | Maps to |
|---|---|---|
| 19:36:34.9 | client `0064` (login) → `0AC4` session `57e8b2e4/2ecfa6a5`, state 1→2, server list printed | **first login attempt** |
| ~29 s gap | no `0065`, no char-server packets | **first attempt stalls → user retries** |
| 19:37:04.9 | client `0064` again → `0AC4` session `9215e533/54e8eb86` | **manual retry (step 2-3)** |
| 19:37:05.7 | `[XKore fix]` rewrite; client `0065` (char-server enter) | **after server-selection (step 4)** |
| 19:37:05.8 | server char list (`082D`+`006B`+trailer); state 2→3; "Received characters" | OpenKore parses list (step 5) |
| — | no `0066`, no disconnect, log ends | client hangs, never shows char-select |

The ~29 s gap between the two `0064` is the visible signature of
"first attempt hangs on Connecting, user retries."

## Windows crash/hang evidence (read-only)

- **2026-11-05 19:35:07 — EventID 1001 (WER) `AppHangB1` + 1002 (Application
  Hang), `Ragnarok.exe`.** P3 `68779440`, P5 `134217728` (0x08000000 = hang).
  This is the **only** failure event today. It means the client **stopped
  responding while waiting**, then was closed. No archived AppHang dump was
  retained (only the Event Log record).
- **No `perl-roz.exe` (OpenKore) crash on 2026-11-05.** OpenKore stayed alive
  (its 19:36–19:37 log continues cleanly). The relay process did not die.
- **No `Ragnarok.exe` exception on 2026-11-05.** Today's failure is a hang,
  not an access violation.
- **2026-11-02 (older, C:\ROZCLUB era):** repeated `Ragnarok.exe` **APPCRASH /
  BEX `c0000005`** (DEP, fault module Ragnarok.exe @ `009bd351`/`001d1772`,
  also `dbghelp.dll`, and `c00001a5`) — hard exceptions. Plus repeated
  **`perl-roz.exe` `c0000005` in `perl530.dll` @`001702ac`** and a
  `libstdc++-6.dll` fatal — i.e. OpenKore's own runtime was crashing that day.
  Report.wer AppPath = `C:\ROZCLUB\Ragnarok.exe`.

### Crash classification asked for

- **Exception:** only Nov 2 (`c0000005`/BEX in Ragnarok.exe; OpenKore perl-roz
  crashes). Not today.
- **Clean exit:** not evidenced anywhere (no orderly exit-0 record).
- **Hang → external close:** **today's mode.** `AppHangB1` = UI thread blocked;
  the process "exit" in step 6 is a hung app being closed (user or Windows),
  not a self-exit and not an exception.

## Reassessed conclusions

**Confirmed**
- Today's client failure is a **hang (AppHangB1)**, i.e. the client is **blocked
  waiting on the connection**, not crashing on data. A hang (not a c0000005)
  argues the client is waiting for bytes/socket events it never gets — a
  transport/relay-completion class of problem — rather than choking on a
  malformed char list (that would crash, as on Nov 2).
- **OpenKore and Ragnarok.exe diverge in connection state** on the successful
  attempt: OpenKore reaches state 3 ("received characters") while the client is
  still "Connecting to server" and never renders char-select. OpenKore treats
  the char-server exchange as complete; the client does not.
- **OpenKore did not crash today**; the relay was up. So the client's hang is
  not caused by the proxy process dying.
- The first-login failure is a **stall before the char-server step** (login/
  `0AC4` received, then ~29 s with no `0065`), worked around by a manual retry —
  distinct from the post-selection hang, though both present as "Connecting to
  server".

**Earliest confirmed failure**
- First attempt: the **login-server → char-server transition stalls** (no
  `0065` for ~29 s after `0AC4`). This is the earliest confirmed break, and it
  is a connection/transport stall, not a parse error.
- Successful attempt: the earliest divergence is **after the char list is
  parsed** — the client does not advance from "Connecting" to char-select; today
  that terminates as `AppHangB1`.

**Cannot be concluded from available evidence**
- Whether the char-list bytes actually reached Ragnarok.exe on the successful
  attempt (OpenKore-side logs only; no client/loopback capture of that run).
- Which socket/module the hung UI thread was blocked on — no AppHang dump was
  archived (WER kept only the Event Log entry; the referenced `WER.*.tmp` files
  are gone).
- Whether the stall/hang is (a) NetRedirect not delivering OpenKore's forwarded
  bytes to the client, (b) the client's redirected char-server/map-server
  connection not completing, or (c) a client-integrity hold. These remain
  competing hypotheses; the hang (vs exception) slightly favours (a)/(b)
  (waiting on I/O) over a data-rejection crash.

## The evidence that would decide it (read-only; needs a live run — not done)

1. A **full-memory AppHang dump** of Ragnarok.exe at the hang (WER can be set to
   keep it, or capture with a user-mode dump) → the hung thread's call stack
   shows exactly which `recv`/socket/module it is blocked on.
2. A **loopback capture** of the successful attempt correlated to the hang →
   whether the client received `[accountID]082D 006B 09A0 020D 08B9` intact and
   what it did next (idle wait vs FIN/RST).
3. Watching whether the **char-server (6121) and map-server** connections are
   actually proxied (they must be, for the list to reach the client).

All three need the live client running, which is outside this task's scope.
