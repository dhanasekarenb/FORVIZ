@echo off
setlocal
cd /d "%~dp0"
title FORVIZ Vision Demo
python test_vision.py
pause
