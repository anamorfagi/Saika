@echo off
cd /d "%~dp0.."
title Saika - packing
chcp 65001 >nul
".venv\Scripts\python.exe" tools\make_package.py
pause
