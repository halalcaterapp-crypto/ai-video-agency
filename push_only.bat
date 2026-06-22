@echo off
cd /d "%~dp0"
echo Pushing committed changes to GitHub...
git push
echo.
echo Done! Railway will redeploy in about 1-2 minutes.
pause
