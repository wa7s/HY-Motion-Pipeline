@echo off
REM ===========================================================================
REM  Build "HY Motion Studio.exe"
REM
REM  Packages the window into a standalone, console-free application. ComfyUI,
REM  Blender and Cascadeur are NOT bundled - the exe drives the copies already
REM  installed on the machine (set in Edit > Preferences). The Blender/video
REM  helper scripts and the CC0 mannequins ARE bundled, so the exe folder works
REM  on its own.
REM
REM  Output:  HY Motion Studio\HY Motion Studio.exe
REM           HY-Motion-Studio-win64.zip   (upload this to a GitHub Release)
REM ===========================================================================
setlocal
cd /d "%~dp0"

set "VENV=app\.venv\Scripts\python.exe"
if not exist "%VENV%" (
    echo Creating the build environment in app\.venv ...
    py -3.11 -m venv app\.venv 2>nul || py -3 -m venv app\.venv || goto :nopython
)

echo.
echo === Checking build dependencies ===
"%VENV%" -m pip install --quiet --upgrade -r app\requirements.txt || goto :fail

echo.
echo === Cleaning previous build ===
if exist "build"  rmdir /s /q "build"
if exist "dist"   rmdir /s /q "dist"

echo.
echo === Building (this takes a few minutes) ===
"%VENV%" -m PyInstaller --noconfirm --clean ^
    --name "HY Motion Studio" ^
    --windowed ^
    --icon "app\MotionStudio.ico" ^
    --paths "app" ^
    --add-data "app\viewer\viewer.html;viewer" ^
    --add-data "app\viewer\viewer.js;viewer" ^
    --add-data "app\viewer\vendor;viewer\vendor" ^
    --add-data "app\MotionStudio.ico;." ^
    --add-data "blender\hym_retarget.py;blender" ^
    --add-data "blender\gvhmr_to_smplh_fbx.py;blender" ^
    --add-data "blender\hymotion_to_unity.py;blender" ^
    --add-data "video\probe.py;video" ^
    --add-data "video\vid_trim.py;video" ^
    --add-data "video\make_mask.py;video" ^
    --add-data "Mannequin\Base_Male.fbx;Mannequin" ^
    --add-data "Mannequin\Base_Female.fbx;Mannequin" ^
    --add-data "Mannequin\Quaternius_License.txt;Mannequin" ^
    --add-data "README.md;." ^
    --hidden-import "hymstudio" ^
    --hidden-import "hymstudio.main" ^
    --hidden-import "hymstudio.config" ^
    --hidden-import "hymstudio.pipeline" ^
    --hidden-import "hymstudio.presets" ^
    --hidden-import "hymstudio.history" ^
    --hidden-import "hymstudio.theme" ^
    --hidden-import "hymstudio.widgets" ^
    --hidden-import "hymstudio.prefs" ^
    --exclude-module "tkinter" ^
    --exclude-module "matplotlib" ^
    --exclude-module "PIL" ^
    "app\HYMotionStudio.py" || goto :fail

echo.
echo === Installing ===
if exist "HY Motion Studio" rmdir /s /q "HY Motion Studio"
move "dist\HY Motion Studio" "HY Motion Studio" >nul || goto :fail
rmdir /s /q "build" 2>nul
rmdir /s /q "dist" 2>nul
if exist "HY Motion Studio.spec" del "HY Motion Studio.spec"

echo.
echo === Zipping for release ===
if exist "HY-Motion-Studio-win64.zip" del "HY-Motion-Studio-win64.zip"
powershell -NoProfile -Command "Compress-Archive -Path 'HY Motion Studio' -DestinationPath 'HY-Motion-Studio-win64.zip' -CompressionLevel Optimal" || goto :fail

echo.
echo ===========================================================
echo  BUILD OK
echo.
echo  App:      %~dp0HY Motion Studio\HY Motion Studio.exe
echo  Release:  %~dp0HY-Motion-Studio-win64.zip
echo ===========================================================
pause
exit /b 0

:nopython
echo.
echo [error] Python was not found. Install Python 3.11 from https://www.python.org
pause
exit /b 1

:fail
echo.
echo [error] Build failed - see the messages above.
pause
exit /b 1
