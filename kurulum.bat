@echo off
chcp 65001 >nul
title EBS Motion Studio - Kurulum

echo ========================================
echo   EBS Motion Studio Kurulum
echo ========================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo HATA: Python bulunamadi.
    echo Python 3.13+ kurup tekrar deneyin.
    pause
    exit /b
)

echo Python bulundu.
python --version
echo.

echo Pip guncelleniyor...
python -m pip install --upgrade pip

echo.
echo Gerekli paketler kuruluyor...
python -m pip install pillow tkinterdnd2

echo.
echo FFmpeg kontrol ediliyor...
where ffmpeg >nul 2>nul
if errorlevel 1 (
    echo UYARI: FFmpeg PATH icinde bulunamadi.
    echo FFmpeg kurup PATH'e eklemelisiniz.
    echo https://ffmpeg.org/download.html
) else (
    echo FFmpeg bulundu.
    ffmpeg -version
)

echo.
echo Klasorler olusturuluyor...
if not exist output mkdir output
if not exist projects mkdir projects
if not exist assets mkdir assets
if not exist icons mkdir icons
if not exist themes mkdir themes

echo.
echo requirements.txt olusturuluyor...
(
echo pillow
echo tkinterdnd2
) > requirements.txt

echo.
echo Kurulum tamamlandi.
echo Programi baslatmak icin:
echo python app.py
echo.
pause
