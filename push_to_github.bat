@echo off
cd /d "%~dp0"
echo Configuring git and pushing to GitHub...

git config --global user.email "mushiny@gmail.com"
git config --global user.name "Mushahid"

git add .
git commit -m "Initial commit: AI Video Agency"

git remote remove origin 2>nul
git remote add origin https://github.com/halalcaterapp-crypto/ai-video-agency.git
git branch -M main
git push -u origin main

echo.
echo Done! Check github.com/halalcaterapp-crypto/ai-video-agency
pause
