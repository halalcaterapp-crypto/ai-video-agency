@echo off
cd /d "%~dp0"
echo Pushing update to GitHub (Railway will auto-deploy)...
git add .
git commit -m "Add landing page + /order route for post-payment flow"
git push
echo.
echo Done! Railway will redeploy in about 1-2 minutes.
pause
