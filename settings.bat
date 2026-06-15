@echo off
REM Open the Claude Familiar settings / control panel (no console window).
cd /d "%~dp0"
start "" pythonw -m mascot.control_panel
