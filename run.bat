@echo off  
title MiniMax H3 Cloud Studio  
cd /d %~dp0  
echo ===================================================  
echo   Starting MiniMax H3 Cloud Studio on http://localhost:8989  
echo ===================================================  
start http://localhost:8989  
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8989 --reload  
pause 
