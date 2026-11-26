@echo off
:: Se positionne dans le dossier du .bat (independamment de l'endroit depuis lequel il est lance)
cd /d "%~dp0"
:: Tire les dernieres modifications depuis GitHub
git pull
:: Lance le logiciel avec le Python de l'environnement virtuel
venv\Scripts\python.exe main.py
:: En cas d'erreur au lancement, garde la fenetre ouverte pour lire le message
if %errorlevel% neq 0 pause
