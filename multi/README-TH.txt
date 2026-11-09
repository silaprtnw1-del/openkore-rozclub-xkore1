ระบบ Multi-Instance สำหรับ ROZCLUB + OpenKore (XKore 1)
=========================================================

หลักคิด: 1 ตัวละคร = 1 หน้าต่างเกม + 1 OpenKore + 1 พอร์ต
แต่ใช้ DLL ตัวเดียว (NetRedirect-ROZ-IAT-v4.dll) กับ launcher ตัวเดียว (roz)
ไม่ต้องสร้างไฟล์ใหม่ต่อตัวละครอีกแล้ว

DLL รู้ว่าต้องต่อ OpenKore พอร์ตไหนจากตัวแปร ROZ_XKORE_PORT ในหน้าต่างเกมนั้น
roz จะตั้งค่านี้ให้เองตอนเปิดเกม ถ้าไม่มีตัวแปรนี้ DLL ใช้ 2351 เหมือนเดิม

ไฟล์สำคัญ (ในโฟลเดอร์ OpenKore-ROZCLUB-XKore1)
  instances.json          รายชื่อตัวละคร พอร์ต โฟลเดอร์โปรไฟล์ (แหล่งข้อมูลหลักที่เดียว)
  roz.cmd                 คำสั่งหลัก (เรียก multi\roz.ps1)
  Start-ROZ-All.cmd       ดับเบิลคลิกเพื่อเปิดทุกตัวละคร
  multi\bin\              DLL ที่ build แล้ว + BUILD-INFO.txt
  multi\templates\        แม่แบบ config (base, role-support) และ servers.txt
  instances\<ชื่อ>\       control\ tables\ logs\ ของแต่ละตัวละครใหม่
  (potato7 ใช้โปรไฟล์เดิมที่โฟลเดอร์หลัก ไม่ได้ย้ายหรือแก้)

คำสั่ง (พิมพ์ใน cmd หรือ PowerShell ที่โฟลเดอร์นี้)
  roz list                         ดูรายชื่อ
  roz status                       ตอนนี้ตัวไหนรันอยู่ (pid ของ OpenKore และเกม)
  roz check                        ตรวจพอร์ตซ้ำ / config ไม่ตรงกับ registry / ไม่มี DLL
  roz start kiminoto               เปิด OpenKore + หน้าต่างเกม (ขอสิทธิ์ Administrator)
  roz start all                    เปิดทุกตัว ทีละตัว
  roz start kiminoto -NoGame       เปิดเฉพาะ OpenKore
  roz start kiminoto -DryRun       แสดงคำสั่งที่จะรัน ไม่เปิดอะไรจริง
  roz new <ชื่อ> -Follow <หัวหน้า>   สร้างตัวละครซัพพอร์ตใหม่ (หาพอร์ตว่างให้เอง)
  roz new <ชื่อ> -CloneFrom <ตัวละคร>  สร้างโดยคัดลอกจากตัวที่มีอยู่ (เช่น ฟาร์มเมอร์ตัวที่สอง)
  roz remove <ชื่อ> [-DeleteFiles]  เอาออกจากรายชื่อ (ต้องปิดตัวละครนั้นก่อน)
  roz build                        build DLL ใหม่จากซอร์ส OpenKore (ปิดเกมทุกหน้าต่างก่อน)

เพิ่มตัวละครใหม่ (ตัวอย่าง)
  1. roz new aco2 -Follow potato7
  2. roz start aco2
  3. ล็อกอินตัวละครในหน้าต่างเกมใหม่ แล้วเชิญเข้าตี้

หมายเหตุ
  - OpenKore ของแต่ละตัวต้องใช้พอร์ตไม่ซ้ำกัน (roz check จะเตือนถ้าซ้ำ)
  - ตัวละครใหม่ได้ tables\servers.txt ที่ charBlockSize 175 (ค่าที่ถูกของเซิร์ฟเวอร์)
    ค่า 155 ในโปรไฟล์ potato7 ทำให้ตัวละครที่ไม่ได้อยู่ช่อง 0 ทำให้ OpenKore error
    ตอนเข้าแมพ roz check จะเตือนเรื่องนี้
  - ปลั๊กอิน market ถูกโหลดเฉพาะ potato7 (มันอ่าน token จากเกมตัวแรกที่เจอ)
