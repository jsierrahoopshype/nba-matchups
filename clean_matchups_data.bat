@echo off
REM Wipe the v1 data so we can regenerate cleanly with the new build scripts.
REM Run this from C:\Users\Jorge Sierra\Documents\nba-matchups

if not exist "data\p" (
    echo data\p folder not found - skipping wipe
) else (
    rmdir /S /Q "data\p"
    echo Deleted data\p
)

if not exist "p" (
    echo p folder not found - skipping wipe
) else (
    REM Keep template.html, wipe the rest
    for /F %%i in ('dir /B "p\*.html" ^| findstr /V "^template.html$"') do (
        del "p\%%i"
    )
    echo Deleted player stubs in p (kept template.html)
)

if exist "data\player_index.json" del "data\player_index.json"
if exist "data\pairs_top.json" del "data\pairs_top.json"
if exist "data\meta.json" del "data\meta.json"

echo Done. Ready to regenerate.
