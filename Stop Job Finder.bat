@echo off
curl -s -X POST http://localhost:8765/api/shutdown >nul 2>&1 && (echo Job Finder stopped.) || (echo Job Finder was not running.)
timeout /t 3 >nul
