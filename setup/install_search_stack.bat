@echo off
setlocal
cd /d "%~dp0.."
title Saika - умный поиск (trafilatura + ddgs + uBlock)
chcp 65001 >nul
echo.
echo  Ставлю то, на чём держится нормальный поиск:
echo.
echo   trafilatura - выдирает ТЕКСТ СТАТЬИ без меню, футеров и "читайте
echo                 также", и достаёт ДАТУ публикации. Без неё Сайка не
echo                 отличает свежую новость от прошлогодней.
echo   ddgs        - выдача поисковика без разбора вёрстки: не ломается
echo                 при редизайне и отдаёт десятки ссылок сразу.
echo.
".venv\Scripts\python.exe" -m pip install --upgrade trafilatura ddgs
echo.
echo  Теперь uBlock Origin - режет баннеры в её окне браузера.
echo.
".venv\Scripts\python.exe" setup\install_ublock.py
echo.
echo  Готово. Перезапусти Сайку (start.bat).
echo.
pause
endlocal
