# Actualiza las dependencias del proyecto a las versiones sin vulnerabilidades conocidas
# (generado por el escaneo de seguridad del 2026-09-26). Todo queda registrado en actualizar_dependencias.log
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$log = Join-Path $root 'actualizar_dependencias.log'
"==== Inicio $(Get-Date -Format s) ====" | Tee-Object -FilePath $log

function Run($title, $cmd) {
    "`n### $title" | Tee-Object -FilePath $log -Append
    "> $cmd"        | Tee-Object -FilePath $log -Append
    Invoke-Expression "$cmd 2>&1" | Out-String -Stream | Tee-Object -FilePath $log -Append
    "### exit code: $LASTEXITCODE" | Tee-Object -FilePath $log -Append
}

$py = Join-Path $root 'virtual-enviroment\Scripts\python.exe'
if (-not (Test-Path $py)) { "ERROR: no se encontro $py" | Tee-Object -FilePath $log -Append; Read-Host 'Pulsa Enter para salir'; exit 1 }
$npm = 'C:\Program Files\nodejs\npm.cmd'
if (-not (Test-Path $npm)) { $npm = 'npm' }

Run 'Python del entorno virtual' "& '$py' --version"
Run 'pip freeze ANTES' "& '$py' -m pip freeze | Out-File -Encoding utf8 '$root\pip_freeze_antes.txt'; Get-Content '$root\pip_freeze_antes.txt' | Measure-Object -Line | Select-Object -ExpandProperty Lines"
Run 'Desinstalar paquetes retirados (tailwind equivocado, alpha_vantage y el arbol de aiohttp)' "& '$py' -m pip uninstall -y tailwind alpha_vantage aiohttp aiohappyeyeballs aiosignal frozenlist multidict yarl propcache attrs"
Run 'Instalar requirements.txt + requirements-dev.txt (versiones corregidas)' "& '$py' -m pip install -r requirements-dev.txt"
Run 'Reinstalar django-tailwind (restaura los archivos que compartia con el paquete tailwind)' "& '$py' -m pip install --force-reinstall --no-deps django-tailwind==4.5.0"
Run 'pip check (consistencia de dependencias)' "& '$py' -m pip check"
Run 'pip freeze DESPUES' "& '$py' -m pip freeze | Out-File -Encoding utf8 '$root\pip_freeze_despues.txt'; Get-Content '$root\pip_freeze_despues.txt' | Measure-Object -Line | Select-Object -ExpandProperty Lines"
Run 'Django: manage.py check' "& '$py' manage.py check"
Run 'pip-audit del entorno virtual' "& '$py' -m pip_audit --progress-spinner off"
Run 'pip-audit de requirements.txt (produccion)' "& '$py' -m pip_audit -r requirements.txt --progress-spinner off"

Set-Location (Join-Path $root 'theme\static_src')
Run 'npm update (actualiza package-lock.json dentro de los rangos de package.json)' "& '$npm' update"
Run 'npm audit' "& '$npm' audit"
Run 'npm run build (recompila el CSS de Tailwind)' "& '$npm' run build"
Set-Location $root

"`n==== Fin $(Get-Date -Format s) ====" | Tee-Object -FilePath $log -Append
Write-Host "`nListo. El registro completo esta en actualizar_dependencias.log" -ForegroundColor Green
Read-Host 'Pulsa Enter para cerrar'
