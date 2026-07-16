@echo off
:: fix_pagefile.bat — увеличивает файл подкачки Windows до 16-32 ГБ, чтобы
:: Qwen3-TTS и другие модели не падали с "os error 1455" (нехватка commit
:: charge / файла подкачки). Запрашивает права администратора и запускает
:: fix_pagefile.ps1. После — нужна перезагрузка.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -File \"%~dp0fix_pagefile.ps1\"'"
