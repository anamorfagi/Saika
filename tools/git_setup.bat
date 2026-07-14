@echo off
cd /d "%~dp0.."
title Saika - git setup

where git >nul 2>&1
if errorlevel 1 (
    echo [X] git not found. Install it:  winget install Git.Git
    pause
    exit /b 1
)

if not exist ".git" (
    echo [*] Initializing repository, branch: main
    git init -b main
)

rem -- commit identity AFTER init (needs an existing repo for local config)
git config user.name >nul 2>&1
if errorlevel 1 git config user.name "Anamorf"
git config user.email >nul 2>&1
if errorlevel 1 git config user.email "anamorf.agi@gmail.com"

git add -A
git commit -m "Saika: working snapshot"
if errorlevel 1 echo (nothing to commit)

rem -- development branch
git rev-parse --verify dev >nul 2>&1
if errorlevel 1 git branch dev
git checkout dev

echo.
git status -sb
echo.
echo  Done: main = stable, dev = development (you are on dev now).
echo  Back to stable:   git checkout main
echo  Merge dev to main: git checkout main ^&^& git merge dev
pause
