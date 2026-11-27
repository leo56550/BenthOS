@echo off
setlocal EnableDelayedExpansion
title Installation BenthOS

echo.
echo  =========================================
echo       Installation de BenthOS
echo  =========================================
echo.

:: Verifier winget
winget --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] winget n'est pas disponible sur ce systeme.
    echo          Installez "App Installer" depuis le Microsoft Store puis relancez.
    pause
    exit /b 1
)

set NEED_PATH_REFRESH=0

:: Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [1/4] Installation de Python 3.12...
    winget install --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo [ERREUR] L'installation de Python a echoue.
        pause & exit /b 1
    )
    set NEED_PATH_REFRESH=1
) else (
    echo [1/4] Python deja installe.
)

:: Git
git --version >nul 2>&1
if errorlevel 1 (
    echo [2/4] Installation de Git...
    winget install --id Git.Git --silent --accept-package-agreements --accept-source-agreements
    if errorlevel 1 (
        echo [ERREUR] L'installation de Git a echoue.
        pause & exit /b 1
    )
    set NEED_PATH_REFRESH=1
) else (
    echo [2/4] Git deja installe.
)

:: Rafraichir le PATH uniquement si winget vient d'installer quelque chose
if "%NEED_PATH_REFRESH%"=="1" (
    for /f "tokens=*" %%P in ('powershell -NoProfile -Command ^
      "[Environment]::GetEnvironmentVariable(\"PATH\",\"Machine\") + \";\" + [Environment]::GetEnvironmentVariable(\"PATH\",\"User\")"') do set "PATH=%%P"
)

:: Cloner ou mettre a jour le depot
set INSTALL_DIR=%USERPROFILE%\BenthOS
if not exist "%INSTALL_DIR%\.git" (
    echo [3/4] Telechargement de BenthOS...
    git clone https://github.com/leo56550/BenthOS.git "%INSTALL_DIR%"
    if errorlevel 1 (
        echo [ERREUR] Le clonage a echoue. Verifiez votre connexion internet.
        pause & exit /b 1
    )
) else (
    echo [3/4] BenthOS deja present, mise a jour...
    cd /d "%INSTALL_DIR%"
    git pull
)

cd /d "%INSTALL_DIR%"

:: Environnement virtuel + dependances
echo [4/4] Installation des dependances Python...
if not exist "venv" (
    python -m venv venv
)
venv\Scripts\pip install --upgrade pip --quiet
venv\Scripts\pip install -r requirements.txt
if errorlevel 1 (
    echo [ERREUR] L'installation des dependances a echoue.
    pause & exit /b 1
)

echo.
echo  Installation terminee !
echo  BenthOS est installe dans : %INSTALL_DIR%
echo  Pour lancer le logiciel, double-cliquez sur lancer.bat dans ce dossier.
echo.
pause
