# HANDOFF — ROZ Bot Control: Auto login / relogin (2026-11-10)

> สำหรับ Claude (เอเจนต์คนถัดไป) + ผู้ใช้
> อ่านไฟล์นี้ก่อน แล้วอ่าน `README.md`, `git status`, และภาพดีบักล่าสุด
> **งาน 4a (เพิ่ม/ลบบอท) commit แล้ว แต่ auto login ยังไม่ผ่านการทดสอบกับเกมจริง และยังไม่ commit**

---

## 0. TL;DR (อ่านก่อน)

- เป้าหมาย: บอท ROZCLUB (OpenKore XKore 1) หลุดแล้ว **ล็อกอิน + เลือกเซิร์ฟเวอร์ + เลือกตัวละคร + กลับเข้าเกมเอง** โดยไม่ต้องเฝ้าจอ
- ทำเสร็จแล้ว: โมดูล auto login, หน้าตั้งค่า, เก็บรหัส DPAPI, ตรวจการหลุด, เลือกเซิร์ฟเวอร์/ตัวละคร, retry/แจ้งเตือน, `roz game`/`gamepid`
- **ปัญหาค้างล่าสุด (02:40)**: ระบบผ่านหน้า login ไปถึงหน้า **เลือกเซิร์ฟเวอร์** แล้วคลิก OK แต่มี dialog **"อีเว้นท์ — เชื่อมต่อเซิฟเวอร์ล้มเหลว"** เด้งทับหน้าเลือกเซิร์ฟเวอร์ (แถว `Rozclub` น่าจะยังไม่ถูกเลือกก่อนกด OK) จึงยังไม่ถึงหน้าเลือกตัวละคร
- สิ่งที่ต้องทำต่อทันที: แก้ `select_server()` ใน `gui/rozgui/relogin.py` ให้ **ปิด Event/Error ก่อน → คลิกแถวเซิร์ฟเวอร์ให้เลือกจริง → กด OK → ถ้า Event เด้งอีกให้ปิดแล้วลองซ้ำ** (รายละเอียด §6)
- **อย่าแตะ/อ่าน/commit** `%APPDATA%\ROZBotControl\accounts.json` หรือ `settings.json` (มีรหัสผ่าน/Token) — ใช้เฉพาะตอน GUI รัน
- อย่า commit ไฟล์ runtime ของผู้ใช้ (`instances.json`, `bots/...`) หรือภาพดีบัก — ดู §9

---

## 1. สภาพแวดล้อมและพาธ

| อะไร | พาธ |
|---|---|
| โปรเจกต์ | `C:\Users\silap\OneDrive\Desktop\Pannapa Farm Redesign\OpenKore-ROZCLUB-XKore1` |
| OpenKore | `C:\Users\silap\openkore` |
| เกม | `D:\ROZCLUB` (`Ragnarok.exe`) |
| Python ที่ GUI ใช้ | `C:\Users\silap\miniconda3\pythonw.exe` (Pillow/truststore มีอยู่) |
| Registry บอท | `instances.json` (ตอนนี้มี potato7, kiminoto, swordman) |
| โปรไฟล์บอท | `bots\<ชื่อ>\{control,tables,logs}` |
| ตั้งค่า GUI | `%APPDATA%\ROZBotControl\settings.json` (Telegram/Discord) |
| รหัสผ่าน auto login | `%APPDATA%\ROZBotControl\accounts.json` (DPAPI, **ห้าม commit/อ่าน/พิมพ์**) |
| ภาพดีบัก auto login | `%APPDATA%\ROZBotControl\relogin-debug\<บอท>-<เวลา>\` |

สถานะ git ตอนเขียนเอกสาร:

- HEAD = `481253d GUI: add and remove bots through roz.ps1 new/remove`
- `origin/main` = `b1f9f5d Restructure: one folder per bot, scripts/, src/, docs/`
- branch `main` **ahead 1** (4a ยังไม่ push)
- auto login + handoff นี้ **ยังไม่ commit** (รายการใน §8)

สถานะ runtime ตอน 02:43:

- `potato7`: OpenKore pid 8560, game pid 2032, `status.json` `online:0`, `state:2`, `char:""` — เกมอยู่ช่วง login/master server
- `kiminoto`: online, state 5, map `payon`, char `kiminoto`
- `game.pid`: potato7 = 2032, kiminoto = 14412
- `accounts.json` มีอยู่ (698 bytes, แก้ล่าสุด 02:42) — **ห้ามเปิดอ่านในเอกสาร/commit**
- debug ล่าสุด: `relogin-debug\potato7-20261110-024009\`
- `roz check` = OK (3 instances, DLL present)

---

## 2. ประวัติการแก้ (timeline)

| เวลา | เหตุการณ์ |
|---|---|
| 00:14 | commit `b1f9f5d` restructure: `bots/<name>`, `scripts/`, `src/native/`, `docs/` |
| 01:32 | commit `481253d` **4a**: เพิ่ม/ลบบอทจาก GUI ผ่าน `roz.ps1 new/remove` (ทดสอบผ่าน) |
| 01:44–01:53 | เริ่ม auto login: DPAPI, SendInput, หน้าตั้งค่า, ตรวจการหลุด, `roz game`/`gamepid` |
| 02:14 | ทดสอบจริงครั้งแรก: login ผ่าน แต่หน้า **เลือกเซิร์ฟเวอร์** ขึ้นมา; โค้ดเก่าคิดว่าเป็นหน้าเลือกตัวละคร → ค้าง |
| 02:15 | ทดสอบซ้ำ; ภาพ `04-after-login` = server, `05-char-select` ยังเป็น server, `06-timeout` |
| 02:16 | ผู้ใช้แจ้งว่า “login เสร็จมีหน้าเลือก server ก่อน” |
| 02:17–02:26 | เพิ่ม `server_slot`/`server_delay`, ตรวจ dialog แบบ top-level/child, คลิก IDOK/ListView, ข้าม login ถ้า server dialog เปิดอยู่, ใช้ state 4/5 |
| 02:40 | ทดสอบล่าสุด: ผ่าน login → server; แต่ `06-char-select.png` เป็น dialog **อีเว้นท์ “เชื่อมต่อเซิฟเวอร์ล้มเหลว”** ทับหน้า server; ยังไม่ถึง char |
| 02:42 | ผู้ใช้กดบันทึกค่าใน GUI (accounts.json อัปเดต) |
| 02:43 | เขียน handoff นี้ |

ภาพที่เกี่ยวข้อง (local):

- `%APPDATA%\ROZBotControl\relogin-debug\potato7-20261110-021505\04-after-login.png` — หน้าเลือกเซิร์ฟเวอร์
- `...\potato7-20261110-024009\05-server-select.png` — หน้า server ก่อนคลิก
- `...\potato7-20261110-024009\06-char-select.png` — **Event “เชื่อมต่อเซิฟเวอร์ล้มเหลว” ทับหน้า server** ← ปัญหาปัจจุบัน

---

## 3. 4a ที่ commit แล้ว (`481253d`)

**เพิ่ม/ลบบอทจาก GUI** — ทำงานและผู้ใช้ยืนยันแล้ว:

- ปุ่ม `➕ เพิ่มบอท` / `➖ ลบบอท` ที่แถบซ้าย
- หน้าต่างเพิ่มบอท: ชื่อ `a-z 0-9 _ -`, คัดลอกจากบอทที่มี หรือ Support (เดินตาม), Port auto/กำหนดเอง, แสดงผล/error ของ `roz.ps1`, โหลดรายชื่อใหม่ทันที
- ลบบอท: เก็บ/ลบโฟลเดอร์, กันลบตอนบอท Running
- ไฟล์ใน commit: `README.md`, `gui/rozgui/app.py`, `gui/rozgui/bot.py`, `scripts/templates/servers.txt` (IP เป็น `15.235.236.242`)

---

## 4. Auto login ที่ทำไว้ (ยังไม่ commit)

### 4.1 หลักการ

XKore 1 ให้ **เกมเป็นคนล็อกอิน/เลือกตัวละคร**; OpenKore แค่ relay packet
`plugins/reconnect` ข้าม XKore 1/3; หลุดแล้ว OpenKore จะ **รอ client** (ไม่ล็อกอินให้)
จึงต้องขับหน้าต่างเกมด้วย Win32 `SendInput`

### 4.2 ลำดับการทำงาน (`LoginRunner.run` ใน `gui/rozgui/relogin.py`)

1. ตรวจ `is_admin()`; ถ้าไม่ใช่ admin → abort (UIPI บล็อก SendInput ไปเกม elevated)
2. หาเกม pid/หน้าต่าง; โฟกัส; ถ้าโฟกัสไม่ได้ → abort (กันพิมพ์รหัสผ่านลงหน้าต่างอื่น)
3. อ่าน state จาก `status.json`:
   - `state == 5` หรือ `-1` → ถือว่าออนไลน์อยู่แล้ว → จบ
   - `state == 4` (character server) → ข้าม login/server ไปเลือกตัวละคร
4. ถ้ามี **server dialog** เปิดอยู่แล้ว → ข้าม login
5. ถ้าไม่มี: ปิด Disconnected/Error (ยกเว้น server) → รอ `login_delay` → พิมพ์ username/password → Enter
6. รอ `server_delay` → เจอ server dialog → เลือกแถว + OK
7. รอ `char_delay` → โฟกัสเกม → Down `char_slot-1` ครั้ง → Enter
8. รอ `online` สูงสุด `map_timeout`

### 4.3 หน้าตั้งค่า (`gui/rozgui/logintab.py`)

แท็บ **ตั้งค่าบอท → ล็อกอินอัตโนมัติ** ต่อบอท:

- เปิด/ปิด auto login
- Username / Password (แสดงเป็นจุด)
- ตัวละครช่องที่ (1–12)
- **เซิร์ฟเวอร์ช่องที่ (1–20)** ← เพิ่มเพราะมีหน้าเลือก server
- ดีเลย์: login / **server** / char / map timeout
- จำนวนครั้ง, เวลาถือว่าหลุด, cooldown
- ปุ่ม บันทึก / ทดสอบ / เปิดโฟลเดอร์ภาพดีบัก
- เตือนถ้า GUI ไม่ได้เป็น Administrator + ปุ่มเปิดใหม่แบบ admin
- **ปุ่ม “บันทึก” ของแท็บนี้แยกจากปุ่มบันทึกด้านบน**

### 4.4 ความปลอดภัย

- รหัสผ่านเข้ารหัส **Windows DPAPI** (`CryptProtectData`) ที่ `accounts.json` — ถอดได้เฉพาะ user นี้
- ไม่เขียนลง `config.txt` (ไฟล์ tracked) และไม่ log รหัสผ่าน
- `Start-GUI-Admin.cmd` เปิด GUI elevated (UAC 1 ครั้ง) เพื่อให้ SendInput ไปเกม elevated ได้
- ถ้าโฟกัสไม่ใช่หน้าต่างเกม → abort ทันที (ไม่พิมพ์รหัสลงแอปอื่น)
- ปิด Caps Lock ก่อนพิมพ์
- จำกัด 3 ครั้ง/รอบ กันล็อกบัญชี

### 4.5 ตัวตรวจการหลุด (`App._maybe_recover`)

- เริ่มเมื่อ:
  - มี dialog (Disconnected/Error/server) **หรือ**
  - `state == 4` (ค้างหน้าเลือกตัวละคร) **หรือ**
  - อยู่ใน login episode ที่เริ่มจาก dialog แล้ว
- ต้องมี: `enabled`, มี user/pass, admin, OpenKore ยังไม่ตาย, มี game pid/หน้าต่าง
- ทำงานทีละบอท (`_recovery_active`)
- retry ตาม `cooldown_seconds`; ครบ `retries` แล้วหยุดและแจ้งเตือน (กันล็อก)
- สำเร็จ/ล้มเหลว → feed + Telegram/Discord ผ่่าน `Notifier`

---

## 5. ไฟล์ที่เพิ่ม/แก้ (auto login — ยังไม่ commit)

| ไฟล์ | สถานะ | สิ่งที่ทำ |
|---|---|---|
| `gui/rozgui/relogin.py` | **ใหม่** (~30 KB) | DPAPI, Win32 window/dialog/focus/SendInput, `LoginRunner`, server/char steps, screenshots |
| `gui/rozgui/logintab.py` | **ใหม่** (~18 KB) | แท็บตั้งค่า auto login + save/test/admin |
| `Start-GUI-Admin.cmd` | **ใหม่** | เปิด GUI elevated ผ่าน UAC |
| `gui/rozgui/app.py` | แก้ | เพิ่มแท็บ, จำ game pid, monitor/auto recovery, retry/cooldown, feed/notify |
| `gui/rozgui/bot.py` | แก้ | `run_roz()`, `game.pid` cache/discover, `remember_game_pid` |
| `scripts/roz.ps1` | แก้ | `roz game <name>`, `roz gamepid <name>`, เขียน `logs/game.pid`, แยก `Start-GameClient` |
| `README.md` | แก้ | วิธีใช้/ข้อจำกัด auto login, `Start-GUI-Admin.cmd`, `roz game/gamepid` |
| `HANDOFF.md` | ใหม่ (ไฟล์นี้) | handoff/history |

Diff โดยประมาณ (เฉพาะไฟล์ source): `app.py +171`, `bot.py +31`, `scripts/roz.ps1 +131/-27`, `README.md +24/-1` (ตัวเลขอาจเปลี่ยนเล็กน้อย)

---

## 6. ปัญหาที่ต้องแก้ทันที: server dialog + Event “เชื่อมต่อเซิฟเวอร์ล้มเหลว”

### อาการล่าสุด (02:40)

1. login ผ่าน
2. หน้า **เลือกเซิร์ฟเวอร์** (Win32 dialog, รายการ `Rozclub`, ปุ่ม OK/ยกเลิก) ขึ้น
3. โค้ดพยายามเลือก/กด OK
4. เกิด dialog **“อีเว้นท์”** ข้อความ **“เชื่อมต่อเซิฟเวอร์ล้มเหลว”** ทับหน้าเลือกเซิร์ฟเวอร์
5. ยังไม่ถึงหน้าเลือกตัวละคร (`06-char-select.png` คือภาพ Event นี้)

### สาเหตุที่น่าจะเป็น

`select_server()` ใน `relogin.py` ปัจจุบัน:

```python
listbox = find_child_class(server.hwnd, 'ListBox')
if listbox:
    SendMessageW(listbox, LB_SETCURSEL, server_slot-1, 0)
else:
    press(DOWN) ...          # ถ้า focus ไม่ได้ผล
click_dialog_button(server.hwnd)   # <-- กด OK ทันที
wait(1.0)
if find_server_dialog(...):        # fallback หลังจากเกิดเรื่องแล้ว
    lv = find_child_class(..., 'SysListView32') or listbox
    click_relative(lv, ...)
    click_dialog_button(...)
```

- หน้า server น่าจะเป็น **SysListView32 (มี header)** ไม่ใช่ ListBox → `LB_SETCURSEL` ไม่ทำงาน
- `press(DOWN)` อาจไม่ถูกโฟกัสที่ list
- จึงกด OK โดย **ยังไม่ได้เลือกแถว `Rozclub`** → เกมพยายามเชื่อมต่อเซิร์ฟเวอร์ที่ยังไม่ถูกเลือก → “เชื่อมต่อเซิฟเวอร์ล้มเหลว”
- fallback ไปคลิก ListView **หลังจาก** Event เด้งแล้ว; Event เป็น modal ทับ ทำให้คลิกข้างหลังไม่ได้ผล
- `find_server_dialog` ยังเห็น server dialog ที่อยู่ข้างหลัง Event → เข้าใจว่าปิด server ไม่ได้

### แนวทางแก้ (ทำใน `select_server`)

1. **ตอนเริ่ม `select_server`**: เรียก `self.dismiss_dialog(main, cancel)` ก่อน (มันกรอง server ออกอยู่แล้ว) เพื่อปิด Event/Error ที่อาจค้างจากรอบก่อน
2. **หา list control**:
   - `ListBox` → `LB_SETCURSEL` (0x0186) index `server_slot-1`
   - `SysListView32` → **คลิกแถว server ก่อน** ด้วย `click_relative(lv, 0.25, 0.13 + 0.09*(slot-1))`
     - ค่า y มาจากภาพ 02:40: dialog สูง ~203px, list มี header, แถวแรก centre ~0.13 ของ list client
   - ไม่พบทั้งคู่ → `click_relative(server.hwnd, 0.5, 0.17 + 0.09*(slot-1))`
3. **รอ 0.3–0.5 วิ** ให้ selection เกิด
4. `click_dialog_button(server.hwnd)` (IDOK = GetDlgItem 1, `BM_CLICK`)
5. รอ 1–1.5 วิ
6. ถ้ามี **dialog ที่ไม่ใช่ server** (Event/Error):
   - `self.dismiss_dialog(main, cancel)` เพื่อกด OK ปิดมัน
   - หา server dialog ใหม่ แล้ว **เลือกแถว + OK ซ้ำ** (สูงสุด 2 รอบ)
7. ถ้า server dialog ยังอยู่ → `self.shot('server-stuck')`, log, return False
8. ถ้า server dialog หาย → log สำเร็จ → ไป char

**ข้อควรระวัง**

- อย่าใช้ `find_dialogs(...)` แบบ any-popup เป็นตัวตัดสินว่า server ยังอยู่; ใช้ `find_server_dialog(...)` เท่านั้น (มี loading/Event ได้)
- Event dialog title “อีเว้นท์” ไม่ใช่ server; `dismiss_dialog` จะจัดการ
- ถ้า ListView ยังเลือกไม่ได้ ให้ใช้ `LVM_SETITEMSTATE` (0x102B) หรือ `LVM_GETITEMRECT` (0x100E) แทนการคลิก; ต้องมี struct `LVITEM`/`RECT`
- อาจต้อง **double-click** แถว server; ลองคลิก 2 ครั้ง (interval ~0.15s) ถ้าคลิกครั้งเดียวไม่พอ
- หลังเลือก server สำเร็จ เกมอาจขึ้น **loading** ก่อน char; `char_delay` 8s อาจต้องเพิ่ม

**ถ้าเลือกแถวแล้วยังขึ้น Event “เชื่อมต่อเซิฟเวอร์ล้มเหลว”**

- ตรวจว่า account นี้ยังล็อกอินค้างจากรอบก่อน (ปิด client เก่า/รอ session หลุด แล้วลองใหม่)
- server อาจเต็ม/ปิดปรับปรุง; ลองใหม่หลัง 30–60 วินาที
- แถว server อาจยังไม่ถูกเลือกจริง (ลอง double-click หรือใช้ `LVM_SETITEMSTATE`)
- ถ้ามีหลายแถว ตรวจ `server_slot` ว่าตรงกับ `Rozclub`
- บันทึกภาพ `05-server-select.png` / หลังคลิก เพื่อดูว่าแถวถูก highlight หรือไม่

### สิ่งที่ต้องตรวจต่อหลังแก้ server

- หน้าเลือกตัวละครเป็น **หน้าต่างเกมหลัก** หรือ **dialog แยก**?
  - ถ้าเป็น dialog แยก (เช่น title “เลือกตัวละคร”) ต้องเพิ่ม `select_character()` คล้าย server (เลือกแถว/OK)
  - ปัจจุบันโค้ดโฟกัส main แล้วกด Down/Enter อย่างเดียว
- หลังเลือก server มี **หน้าเลือก channel** อีกชั้นไหม?
  - ถ้ามี ต้องเพิ่ม step + ค่า delay/slot
- หน้า char ต้อง **double-click** หรือไม่?
- ถ้า `06-char-select.png` ยังเป็น server/Event แสดงว่า server step ยังไม่ผ่าน

---

## 7. วิธีทดสอบ (ทำตามลำดับ)

1. **ปิด GUI เก่า** (ตัวที่รันอยู่จะยังเป็นโค้ดก่อนแก้)
2. เปิด `Start-GUI-Admin.cmd` → Yes ที่ UAC
3. รอให้ GUI เห็นบอท; ตรวจว่าแท็บล็อกอินอัตโนมัติขึ้น ✅ Administrator
4. เลือก `potato7` → แท็บ **ล็อกอินอัตโนมัติ**
   - `เซิร์ฟเวอร์ช่องที่` = **1** (ในภาพมี server เดียว `Rozclub`)
   - `ตัวละครช่องที่` = ช่องจริง (รอบก่อนทดสอบใช้ 1)
   - Username/Password เดิมมีใน `accounts.json` แล้ว (ไม่ต้องพิมพ์ใหม่ ถ้าโชว์จุด)
5. กด **ทดสอบล็อกอินตอนนี้** (ปุ่มนี้ save ให้ก่อน)
   - ถ้าเกมอยู่หน้า login → พิมพ์ให้
   - ถ้า server dialog เปิดอยู่ → ต้องเลือกแถว + OK
   - ถ้า state 4 → ข้ามไป char
6. ดูภาพชุดใหม่ที่ `%APPDATA%\ROZBotControl\relogin-debug\potato7-<เวลา>\`
7. ถ้าผ่าน → ลอง `kiminoto`; แล้วจึงเปิด auto ทั้งสอง

**หมายเหตุ**: ถ้าเกมค้างที่ server dialog ให้กด **ยกเลิก** ในเกม หรือปิด/เปิดเกมใหม่ แล้วทดสอบที่หน้า login เพื่อเริ่มใหม่

---

## 8. Git / สิ่งที่ยังไม่ commit

### ยังไม่ commit (source)

- `Start-GUI-Admin.cmd`
- `gui/rozgui/relogin.py`
- `gui/rozgui/logintab.py`
- `gui/rozgui/app.py`
- `gui/rozgui/bot.py`
- `scripts/roz.ps1`
- `README.md`
- `HANDOFF.md` (ไฟล์นี้)

### ห้าม commit (runtime/ผู้ใช้)

- `instances.json` (ผู้ใช้เพิ่ม `swordman`)
- `bots/swordman/` (บอททดสอบของผู้ใช้)
- `bots/kiminoto/control/config.txt` (ผู้ใช้ปิดสกิลใน GUI)
- `bots/potato7/control/mon_control.txt` + `bots/potato7/control/priority.txt` (GUI เขียน)
- `bots/*/logs/` (รวม `game.pid`, console)
- `gui/gui-error.log`
- `accounts.json`, `settings.json`, `relogin-debug/` (นอก repo อยู่แล้ว)

### หลังแก้ผ่านแล้ว

```powershell
git add Start-GUI-Admin.cmd gui/rozgui/relogin.py gui/rozgui/logintab.py `
        gui/rozgui/app.py gui/rozgui/bot.py scripts/roz.ps1 README.md HANDOFF.md
git commit -m "GUI: auto login/relogin for XKore 1 clients"
git push   # เฉพาะเมื่อผู้ใช้อนุมัติ (origin/main ยังอยู่ b1f9f5d)
```

> commit 4a `481253d` ยังไม่ push; ถ้าจะ push ต้องรวม commit นี้ด้วย

---

## 9. ข้อจำกัด/ความเสี่ยงที่รู้อยู่

- **ต้องรัน GUI เป็น Administrator** และ **ไม่ล็อกจอ/ไม่สลีป**; ถ้าล็อก SendInput ทำไม่ได้
- **UIPI**: GUI ต้อง elevated; ไม่งั้นส่งคีย์ไปเกมไม่ได้
- **DPAPI**: accounts.json ถอดได้เฉพาะ user นี้; ห้าม commit/แชร์
- **ไม่มี PIN/OTP**: ผู้ใช้ยืนยันว่าไม่มี; ถ้ามีจะทำอัตโนมัติไม่ได้
- **หน้า server/char**: ยังไม่ยืนยันว่าใช้คีย์บอร์ด/เมาส์แบบไหน; ถ้า double-click หรือมี channel ต้องเพิ่ม
- **ปิดหน้าต่างเกม**: auto ยังไม่เปิดเกมใหม่ให้; ใช้ `roz game <ชื่อ>` เอง (หรือเพิ่ม elevated helper ภายหลัง)
- **OpenKore ตาย**: auto ไม่ start OpenKore ให้; ต้องกดเริ่มบอท
- **auto trigger**: ต้องมี dialog หรือ state 4; ถ้าเกมกลับ login เองโดยไม่มี dialog และ state 3 จะยังไม่ auto (กดทดสอบเอง)
- **3 ครั้งแล้วหยุด** กันล็อกบัญชี; cooldown default 300s
- **Thai IME/Caps Lock**: ปิด Caps ให้แล้ว; ถ้าภาษาไทยทำให้พิมพ์ผิด อาจต้องบังคับ layout อังกฤษ
- **หน้าต่าง server อาจเป็น child/top-level**: โค้ดรองรับทั้ง `find_dialogs` top-level + `_child_dialogs`; ถ้ายังไม่เจอ ให้ enumerate และ log class จริง
- **ห้ามเพิ่ม package ใหม่** โดยไม่อนุมัติ; ตอนนี้ใช้ stdlib + Pillow ที่มีอยู่

---

## 10. คำถามที่ต้องถามผู้ใช้/ตรวจจากภาพ

1. หน้าเลือกเซิร์ฟเวอร์: ต้อง **คลิกแถว `Rozclub` ก่อน OK** หรือมีแถวถูกเลือกอยู่แล้ว? (ภาพ 02:40 แถวดูไฮไลต์ แต่ Event เกิด)
2. หลังเลือก server สำเร็จ มีหน้า **channel** อีกไหม?
3. หน้าเลือกตัวละครเป็นหน้าต่างเกมหรือ dialog? ต้องดับเบิลคลิกตัวละครหรือกด Enter?
4. ตัวละครที่ต้องการอยู่ช่องไหน (1 = ตัวแรก)?
5. ต้องการให้ auto ทำงานตอนเกมกลับ login โดยไม่มี dialog ด้วยหรือไม่ (ต้องยอมให้พิมพ์รหัสเองอัตโนมัติ)

---

## 11. งานถัดไปหลัง auto login ผ่าน (4b)

ผู้ใช้ระบุลำดับไว้ (ทำทีละส่วน):

1. ขาย / ฝาก / ซื้ออัตโนมัติ (มีรูปไอเทม)
2. ความปลอดภัย: หนี GM/ผู้เล่น + relog
3. หน้าจัดทีมบอท
4. อัปสเตตัส/สกิลอัตโนมัติ (มีหน้ายืนยันก่อน เพราะแจกแล้วคืนไม่ได้)

**อย่าเริ่ม 4b ก่อน auto login ผ่านและ commit**

---

## 12. คำสั่งที่มีประโยชน์

```powershell
# registry / สถานะ
.\roz.cmd check
.\roz.cmd status
.\roz.cmd gamepid potato7
.\roz.cmd game potato7 -DryRun

# เปิด GUI ปกติ / แบบ admin
.\Start-GUI.cmd
.\Start-GUI-Admin.cmd

# GUI tests (mypy): ใช้ uvx ถ้าเครื่องไม่มี mypy
$env:UV_CACHE_DIR="$PWD\.uv-cache-tmp"
$env:UV_TOOL_DIR="$PWD\.uv-tools-tmp"
uvx --python C:\Users\silap\miniconda3\python.exe mypy --strict --python-version 3.14 gui\rozgui
# baseline ที่ยังเหลือ 20 errors (tkinter/PIL/truststore stub) — ต้องไม่มี error ใหม่จาก relogin/logintab
```

---

## 13. หมายเหตุสุดท้าย

- ไฟล์นี้เขียนตอน 02:43 หลังทดสอบ 02:40; สถานะบอทอาจเปลี่ยนได้ ให้ `git status` + ดู `status.json`/`game.pid` ใหม่ก่อนทำงาน
- ภาพดีบักและ `accounts.json` เป็นข้อมูลส่วนตัวของผู้ใช้; อย่าแนบ/commit
- ถ้าต้องการทดสอบแบบไม่แตะบอทจริง ให้ใช้สำเนา `instances.json` + `scripts/roz.ps1` ใน `%TEMP%` ตามที่ทำมาก่อน
- งาน 4a ผ่านการทดสอบของผู้ใช้แล้ว; อย่าแก้ไฟล์ของ 4a โดยไม่จำเป็น
