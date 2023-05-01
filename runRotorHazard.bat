@echo off
pushd %~d0%~p0RotorHazardRun\src\server

if "%1"=="" goto noparam
set sourceFile="%~1"
set destinationFolder="%~d0%~p0RotorHazardRun\src\server\database.db"
copy /y %sourceFile% %destinationFolder%
start ..\..\python38\python server.py --launchb results
goto ex
:noparam
start ..\..\python38\python server.py --launchb results
:ex
popd