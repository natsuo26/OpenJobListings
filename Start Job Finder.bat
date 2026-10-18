@echo off
title Job Finder
cd /d "%~dp0"
python jobfinder.py
if errorlevel 1 pause
