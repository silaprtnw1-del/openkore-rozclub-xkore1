ROZCLUB + OpenKore XKore 1
===========================

สถานะการตั้งค่า
- Client จริง: C:\ROZCLUB\Ragnarok.exe (x86, build 2025-07-16)
- Launcher: C:\ROZCLUB\Rozclub.exe (ส่งต่อ argument ไป Ragnarok.exe)
- Login endpoint: 31.97.223.129:6900
- clientinfo version: 55
- GameGuard: ปิดตามข้อมูลของเจ้าของเซิร์ฟเวอร์
- โหมด: XKore 1, inject เข้า Ragnarok.exe
- รอบแรกตั้ง AI เป็น manual และปิด attack/loot/random walk อัตโนมัติ
- ไม่เก็บ username/password ไว้ในไฟล์ profile นี้
- ใช้ runtime Perl 5.30 x86 แบบแยกเฉพาะ profile เพราะ launcher เดิมชนกับ
  Windows process-mitigation ของเครื่องนี้
- XSTools.dll ถูก build ใหม่สำหรับ Perl 5.30 x86 และทดสอบโหลดได้แล้ว
- ใช้ NetRedirect-ROZ-IAT-v3.dll ซึ่งเปิด DYNAMIC_BASE สำหรับ Windows process-mitigation
  ของเครื่องนี้ โดยเก็บ NetRedirect.dll ต้นฉบับไว้เหมือนเดิม
- launcher ยกระดับเป็น Administrator เนื่องจาก Ragnarok.exe ระบุ
  requireAdministrator; OpenKore สิทธิ์ปกติจึง InjectDLL เข้า process ไม่ได้
- ใช้ roz-xkore-launcher.exe เปิดเกม รอ native loader จัดการ import table เสร็จ
  แล้วตรวจผล LoadLibrary ของ NetRedirect โดยไม่ใช้ injector เก่าของ XSTools
- NetRedirect รุ่นนี้แก้เฉพาะ IAT; ตัด fallback เก่าที่สแกน/เขียน DWORD ทั่ว
  executable image เพราะสามารถทำ code corruption กับ client รุ่นใหม่ได้
- การเชื่อม loopback ของ DLL ใช้ blocking connect หนึ่งครั้งก่อนเปลี่ยน socket
  เป็น nonblocking เพื่อไม่ให้สถานะ connect ระหว่างทางถูกตีความเป็น failure

วิธีเปิด
1. ปิด Ragnarok.exe และ OpenKore เดิมให้หมด
2. เปิด Start-ROZCLUB-XKore1.cmd
3. กด Yes ที่หน้าต่าง UAC เพื่อให้ OpenKore มีสิทธิ์ระดับเดียวกับ Ragnarok.exe
4. รอหน้าต่าง OpenKore แจ้งว่า inject/ready
5. Login ผ่านหน้าต่างเกมตามปกติ

ผลทดสอบที่ผ่านแล้ว
- perl-roz.exe เปิดและรัน Perl code ได้
- XSTools.dll โหลดได้และรายงานเวอร์ชัน 5.8
- openkore.pl --version รันสำเร็จกับ source C:\Users\silap\openkore
- OpenKore อ่าน profile ROZCLUB และเปิด listener 127.0.0.1:2351 สำเร็จ
- แสดง X-Kore mode initialized และรอ Ragnarok.exe สำเร็จ
- roz-xkore-launcher.exe เป็น PE32 x86 และเปิด DYNAMIC_BASE/NX_COMPAT
- NetRedirect-ROZ-IAT-v3.dll ผ่าน local smoke test: โหลด DLL, เชื่อม
  127.0.0.1:2351 และ host ออกด้วย code 0 โดยไม่ crash

หมายเหตุ
- ผู้ใช้ยืนยันว่า client ปกติเข้าเซิร์ฟเวอร์และเข้าแผนที่ได้แล้ว
- ยังต้องยืนยันการเชื่อมต่อผ่าน NetRedirect และ packet compatibility จากรอบทดสอบใหม่
- serverType/recvpackets เริ่มจาก profile ล่าสุดที่มีอยู่ใน source ชุดนี้
  ต้องยืนยันกับ traffic จริงเมื่อเซิร์ฟเวอร์ออนไลน์ก่อนเปิด AI อัตโนมัติ
- การผ่าน smoke test ของ runtime ยังไม่ถือว่า packet profile เข้ากับ client ปี 2025
- ห้ามนำ config tRO/Poseidon เดิมมาปนกับ profile นี้
- ผลการ inject แต่ละรอบเก็บแยกใน logs\injector-YYYYMMDD-HHMMSS.log

