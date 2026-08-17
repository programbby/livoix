@echo off
set /p chemin="Colle le chemin de ton PDF ici puis appuie sur Entree: "
python "%~dp0livoix.py" "%chemin%"
pause
