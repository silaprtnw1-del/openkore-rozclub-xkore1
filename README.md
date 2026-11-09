# ROZCLUB × OpenKore (XKore 1)

บอท OpenKore สำหรับเซิร์ฟเวอร์ ROZCLUB แบบ XKore 1 (บอทเล่นผ่านหน้าต่างเกมจริง) หลายตัวพร้อมกัน
พร้อมโปรแกรมควบคุมแบบหน้าต่าง **ROZ Bot Control**

## ใช้งาน

| ทำอะไร | ไฟล์ |
|---|---|
| เปิดโปรแกรมควบคุม (GUI) | `Start-GUI.cmd` |
| เปิดบอททุกตัว | `Start-ROZ-All.cmd` |
| เปิดทีละตัว | `Start-ROZCLUB-XKore1.cmd` (potato7), `Start-ROZCLUB-XKore1-kiminoto.cmd` |
| คำสั่งจัดการ | `roz list` · `roz status` · `roz check` · `roz start <ชื่อ\|all>` · `roz new …` · `roz remove …` · `roz build` |

การเปิดเกมต้องใช้สิทธิ์ Administrator (มีหน้าต่าง UAC ถาม) เพราะ `Ragnarok.exe` ต้องการสิทธิ์นี้

## โครงสร้าง

```
instances.json        รายชื่อบอท (ชื่อ, port, โฟลเดอร์ profile, role)
roz.cmd, Start-*.cmd  ตัวเปิด (เรียก scripts\roz.ps1)
bots\<ชื่อ>\          profile ของบอทแต่ละตัว: control\ (config) · tables\ · logs\
gui\                  ROZ Bot Control (Python/Tkinter) — rozgui\ คือโค้ด, cache\ คือข้อมูลเกมที่โหลดมา
plugins\gui_ipc\      ปลั๊กอิน OpenKore ที่ส่งสถานะ/รับคำสั่งจาก GUI
plugins\rozclub_market\ ปลั๊กอินสแกนราคาตลาด (คำสั่ง market …)
scripts\              roz.ps1 (ตัวจัดการหลายบอท) · templates\ (แม่แบบ config) · bin\ (NetRedirect DLL ที่ build)
runtime\              Perl 32-bit, XSTools.dll, launcher — ไฟล์ไบนารี ไม่อยู่ใน git
src\native\           source ของโปรแกรม native ใน runtime\
docs\                 บันทึกการตั้งค่าเดิมและผลการวิเคราะห์ (FINDINGS)
tools\                เครื่องมือแยก (packetExtractor มี git ของตัวเอง)
_archive\             ไฟล์ .bak เก่า, packet capture, build เก่า — เก็บไว้ในเครื่อง ไม่อยู่ใน git
```

## สิ่งที่อยู่นอกโปรเจกต์

- OpenKore: `C:\Users\silap\openkore` · เกม: `D:\ROZCLUB` (ตั้งใน `instances.json`)
- การตั้งค่า GUI รวม Telegram token / Discord webhook: `%APPDATA%\ROZBotControl\settings.json`
- ตัวสแกนตลาด: `C:\Users\silap\rearo\rozclub_market_scanner.py` (เขียน `bots\potato7\control\pickupitems.txt`
  และเก็บส่วนที่ GUI ตั้งไว้ท้ายไฟล์ทุกครั้ง)

## git

ไม่เก็บใน git: `logs`, การตั้งค่า GUI (token), cache, ไฟล์ `.bak` และไฟล์ไบนารี (`runtime\`, `*.dll`, `*.exe`)
อย่าใส่รหัสผ่านจริงใน `config.txt` (ช่อง `password` / `storageAuto_password` ว่างไว้)
