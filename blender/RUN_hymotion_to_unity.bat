@echo off
REM ---------------------------------------------------------------------------
REM  HY-Motion FBX  ->  Unity-ready FBX  (via Blender 5.2 headless)
REM
REM  Usage:
REM     RUN_hymotion_to_unity.bat  "in.fbx"  "out.fbx"  [extra args...]
REM
REM  Extra args are passed straight to hymotion_to_unity.py, e.g.:
REM     --rename none        keep raw SMPL-H bone names (for Cascadeur round-trip)
REM     --strip-fingers      drop the 30 finger bones (mobile rigs)
REM     --armature-only      export rig + animation, no skinned mesh
REM     --fps 30             output frame rate (HY-Motion generates at 30)
REM ---------------------------------------------------------------------------
setlocal

REM  Set BLENDER_EXE to use a Blender in another place.
set "BLENDER=%BLENDER_EXE%"
if not exist "%BLENDER%" set "BLENDER=C:\Program Files\Blender Foundation\Blender 5.2\blender.exe"
if not exist "%BLENDER%" set "BLENDER=C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
if not exist "%BLENDER%" set "BLENDER=C:\Program Files\Blender Foundation\Blender 4.5\blender.exe"
if not exist "%BLENDER%" set "BLENDER=C:\Program Files\Blender Foundation\Blender 4.2\blender.exe"
if not exist "%BLENDER%" (
    echo [error] Blender not found. Set BLENDER_EXE to your blender.exe, or edit BLENDER= in this .bat.
    exit /b 1
)

if "%~1"=="" (
    echo Usage: %~nx0 "in.fbx" "out.fbx" [--rename none^|unity] [--strip-fingers] [--armature-only]
    exit /b 1
)
if "%~2"=="" (
    echo [error] missing output path.
    exit /b 1
)

set "SCRIPT=%~dp0hymotion_to_unity.py"
set "SRC=%~f1"
set "DST=%~f2"
shift
shift

echo [hymotion] Blender : "%BLENDER%"
echo [hymotion] in      : "%SRC%"
echo [hymotion] out     : "%DST%"

"%BLENDER%" -b --factory-startup --python "%SCRIPT%" -- --in "%SRC%" --out "%DST%" %1 %2 %3 %4 %5 %6 %7 %8 %9

if errorlevel 1 (
    echo [hymotion] FAILED
    exit /b 1
)
echo [hymotion] done.
endlocal
