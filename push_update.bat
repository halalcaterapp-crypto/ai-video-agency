@echo off
cd /d "%~dp0"
echo Pushing update to GitHub (Railway will auto-deploy)...
git add .
git commit -m "Fix: SyntaxError - escape newline in pipeline.py logger.error string"
git push
echo.
echo Done! Railway will redeploy in about 1-2 minutes.
pause
