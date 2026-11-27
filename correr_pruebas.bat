@echo off
REM Corre TODAS las pruebas de la app con SQLite (test_settings) y guarda el resultado en pruebas_resultado.txt
cd /d "%~dp0"
echo Corriendo pruebas... la ventana se cierra sola al terminar (tarda ~1 minuto).
"virtual-enviroment\Scripts\python.exe" manage.py test finanzas --settings=test_settings --noinput -v 1 > pruebas_resultado.txt 2>&1
