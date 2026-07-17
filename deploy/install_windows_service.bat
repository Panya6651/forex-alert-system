@echo off
REM ==========================================================
REM ติดตั้งระบบเป็น Windows Service ด้วย NSSM
REM (จำเป็นเพราะ MT5 Python API ต้องรันบน Windows เท่านั้น)
REM
REM ก่อนรันสคริปต์นี้:
REM   1. ติดตั้ง Python 3.10+ และรัน: pip install -r requirements.txt
REM   2. ดาวน์โหลด NSSM จาก https://nssm.cc/download แล้ววาง nssm.exe ไว้ใน PATH
REM   3. ตั้งค่าไฟล์ .env ให้ครบ (คัดลอกจาก .env.example)
REM   4. รันสคริปต์นี้ด้วยสิทธิ์ Administrator
REM ==========================================================

set SERVICE_NAME=ForexAutoTradeSystem
set PROJECT_DIR=%~dp0..
set PYTHON_EXE=python

echo กำลังติดตั้ง service: %SERVICE_NAME%
echo Project directory: %PROJECT_DIR%

nssm install %SERVICE_NAME% %PYTHON_EXE% "%PROJECT_DIR%\main.py"
nssm set %SERVICE_NAME% AppDirectory "%PROJECT_DIR%"
nssm set %SERVICE_NAME% AppStdout "%PROJECT_DIR%\logs\service_stdout.log"
nssm set %SERVICE_NAME% AppStderr "%PROJECT_DIR%\logs\service_stderr.log"
nssm set %SERVICE_NAME% AppRotateFiles 1
nssm set %SERVICE_NAME% AppRotateBytes 5242880
REM รีสตาร์ทอัตโนมัติถ้าโปรแกรม crash (สำคัญมากสำหรับระบบเทรด)
nssm set %SERVICE_NAME% AppExit Default Restart
nssm set %SERVICE_NAME% AppRestartDelay 5000
REM รีสตาร์ทอัตโนมัติเมื่อเครื่อง reboot
nssm set %SERVICE_NAME% Start SERVICE_AUTO_START

echo.
echo ติดตั้งเสร็จสิ้น สั่งเริ่มการทำงานด้วยคำสั่ง:
echo   nssm start %SERVICE_NAME%
echo.
echo ดู log แบบเรียลไทม์:
echo   type "%PROJECT_DIR%\logs\system.log"
echo.
echo หยุด service:
echo   nssm stop %SERVICE_NAME%
echo.
echo ถอนการติดตั้ง:
echo   nssm remove %SERVICE_NAME% confirm
pause
