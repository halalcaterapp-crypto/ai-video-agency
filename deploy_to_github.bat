@echo off
echo ============================================
echo  Setting up Git and pushing to GitHub
echo ============================================
cd /d "%~dp0"

git init
git add .
git commit -m "Initial commit: AI Video Agency"

echo.
echo ============================================
echo  Now go to github.com/new and create a
echo  NEW EMPTY repo called: ai-video-agency
echo  (NO readme, NO .gitignore, NO license)
echo  Then paste the repo URL below.
echo ============================================
echo.
set /p REPO_URL="Paste your GitHub repo URL here: "

git remote add origin %REPO_URL%
git branch -M main
git push -u origin main

echo.
echo Done! Your code is on GitHub.
echo Now go back to Claude.
pause
