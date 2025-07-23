@echo off
set NAME=google_ads_downloader

echo Building now...
poetry run pyinstaller src\google_ads_downloader\main.py --name %NAME% --onedir --console --noupx --clean  --collect-all google.ads.googleads.v20 --noconfirm


echo Creating deploy directory...
rmdir /s /q deploy 2>nul
mkdir deploy
xcopy dist\%NAME% deploy\%NAME% /E /I /Y

echo deploy\%NAME% Created!
pause
