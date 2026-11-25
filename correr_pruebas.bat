@echo off
REM Corre las pruebas del presupuesto con SQLite (test_settings) y guarda el resultado en pruebas_resultado.txt
cd /d "%~dp0"
echo Corriendo pruebas... la ventana se cierra sola al terminar.
"virtual-enviroment\Scripts\python.exe" manage.py test finanzas.tests_presupuesto finanzas.tests --settings=test_settings --noinput -v 1 > pruebas_resultado.txt 2>&1
