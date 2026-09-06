@echo off
chcp 65001 >nul
set /p chemin="Colle le chemin de ton PDF ici puis appuie sur Entree: "
set chemin=%chemin:"=%
python "%~dp0livoix.py" "%chemin%"
pause
