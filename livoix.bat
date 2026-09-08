@echo off
setlocal

REM --- Trouver Python : le lanceur "py" d'abord, sinon "python" ---
set PY=
where py >nul 2>nul && set PY=py
if not defined PY where python >nul 2>nul && set PY=python
if not defined PY (
    echo.
    echo Python n'est pas installe sur ce PC.
    echo Telecharge-le ici : https://www.python.org/downloads/
    echo Pense a cocher "Add Python to PATH" pendant l'installation.
    echo.
    pause
    exit /b 1
)

REM --- Installer les dependances au premier lancement ---
%PY% -c "import edge_tts, pdfplumber, langdetect" >nul 2>nul
if errorlevel 1 (
    echo.
    echo Premier lancement : installation des dependances...
    echo.
    %PY% -m pip install -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo.
        echo L'installation a echoue. Verifie ta connexion internet.
        pause
        exit /b 1
    )
)

REM --- Lire le chemin du PDF (avant tout chcp : le code page 65001 casse set /p) ---
set "chemin="
set /p chemin="Colle le chemin de ton PDF ici puis appuie sur Entree: "
if not defined chemin (
    echo.
    echo Aucun chemin saisi.
    pause
    exit /b 1
)
set chemin=%chemin:"=%

REM --- UTF-8 seulement maintenant, pour afficher correctement accents et emojis ---
REM --menu propose la liste des voix francaises ; Entree = detection automatique
chcp 65001 >nul
%PY% "%~dp0livoix.py" "%chemin%" --menu
pause
