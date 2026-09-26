# Escaneo de seguridad de dependencias — finanzas_personales_desarollo

**Fecha:** 26 de septiembre de 2026 · **Rama analizada:** `Dashboarad` (copia de trabajo local) · **Repositorio remoto:** github.com/MicroCloud12/finanzas_personales_desarollo (público)

> Este informe no aplica ningún cambio al proyecto. Todas las actualizaciones se proponen para que se revisen y prueben antes de aplicarlas.

## 1. Resumen ejecutivo

Se analizaron **125 paquetes Python** (`requirements.txt`, que coincide exactamente con lo instalado en `virtual-enviroment/`) y **133 paquetes npm** resueltos en `theme/static_src/package-lock.json` (Tailwind/PostCSS, solo `devDependencies`). Cada paquete se consultó en su versión exacta contra la GitHub Advisory Database y contra OSV (vía deps.dev), y cada aviso se verificó contra el rango de versiones afectado.

Resultado en cifras:

- **Python:** 12 paquetes vulnerables con **76 avisos** (4 críticos, 39 altos, 27 medios, 6 bajos). 30 de esos avisos corresponden a `nltk`, que la aplicación no usa: lo arrastra la herramienta `safety`. Sin `nltk` quedan **46 avisos en 11 paquetes** (1 crítico, 21 altos, 19 medios, 5 bajos).
- **npm (solo herramientas de build):** 9 paquetes vulnerables (10 versiones) con **30 avisos** (1 crítico, 20 altos, 8 medios, 1 bajo). Ninguno se sirve al navegador ni corre en producción; el riesgo se limita a la máquina de desarrollo o al pipeline de build.
- **Cadena de suministro / secretos (lo más urgente):** el archivo `.env` estuvo versionado en git entre el 2 y el 11 de agosto de 2025 y sigue en el historial del repositorio **público**; la `SECRET_KEY` de Django, la contraseña de MySQL y varias claves de API que aparecen ahí **son las mismas que están en uso hoy**. Además, `debug.log` está versionado y en su versión actual (HEAD) contiene 20 veces la clave de `currencyapi.com` dentro de URLs. Estos secretos deben considerarse comprometidos y rotarse.
- **Dependencia equivocada:** `requirements.txt` fija `tailwind==3.1.5b0` (un paquete beta de 2022, de un tercero, que instala un binario `tailwindcss` de 37 MB) pero **no** incluye `django-tailwind`, que es lo que `INSTALLED_APPS` realmente necesita. Ambos escriben en el mismo directorio `site-packages/tailwind/`, así que hoy el entorno funciona por casualidad y una instalación limpia fallaría.

## 2. Alcance y método

Se inventariaron los manifiestos del proyecto (`requirements.txt`, `theme/static_src/package.json` y `package-lock.json` v3), se comprobó que las versiones fijadas coinciden con las instaladas en el entorno virtual (128 distribuciones instaladas: las 125 fijadas más `django-tailwind 4.5.0`, `pytailwindcss 0.3.1` y `pip`), y se consultaron dos fuentes independientes de vulnerabilidades por cada `paquete@versión`: la GitHub Advisory Database (API REST, filtro `affects`) y OSV a través de deps.dev (255 consultas, 0 errores). Los avisos marcados como duplicados o retirados se descartaron, y para cada aviso se verificó con `packaging`/`semver` que la versión instalada cae dentro del rango vulnerable. Las versiones "última disponible" provienen de PyPI/npm vía deps.dev a fecha de hoy.

Limitaciones: el entorno de ejecución de este análisis no tiene salida a PyPI, npm ni osv.dev, por lo que no se ejecutaron `pip-audit`, `npm audit` ni `osv-scanner` directamente; se consultaron las mismas bases de datos que usan esas herramientas. Se recomienda repetir el escaneo con `pip-audit -r requirements.txt` y `npm audit` en la máquina de desarrollo para dejarlo integrado en el flujo habitual (ver sección 7). Se revisó el código de la aplicación solo para determinar qué dependencias se usan directamente y dónde se cargan los secretos; no se hizo una auditoría de código (SAST).

## 3. Hallazgos de cadena de suministro y secretos

### 3.1 Secretos expuestos en el historial de git (crítico)

El repositorio es público en GitHub (309 commits). `.env` fue añadido en el commit `489da1fa` (2025-08-02), modificado en cuatro commits más y eliminado en `948206f6` (2025-08-11, "remove .env file for security reasons"). Eliminar el archivo no lo borra del historial: cualquiera puede recuperarlo con `git show 948206f6^:.env`. Comparando por hash los valores históricos con el `.env` actual (sin mostrar ningún valor), estos secretos **siguen vigentes y están expuestos**:

| Variable | Dónde está expuesta | Estado actual |
|---|---|---|
| `SECRET_KEY` (Django) | 5 versiones de `.env` en el historial | **Mismo valor en uso** |
| `DB_USER` / `DB_PASSWORD` (MySQL) | 5 versiones de `.env` | **Mismo valor en uso** |
| `CONVERT_API_KEY` | 5 versiones de `.env` | **Mismo valor en uso** |
| `TWELVEDATA_API_KEY` | 5 versiones de `.env` | **Mismo valor en uso** |
| `ALPHA_VANTAGE_API_KEY` | 5 versiones de `.env` | **Mismo valor en uso** |
| `MERCADOPAGO_PLAN_ID` | 5 versiones de `.env` | Mismo valor (identificador, no credencial) |
| `CURRENCYAPI_API_KEY` | `debug.log` versionado, 20 líneas en HEAD (commit `e603dc3f`) | **Mismo valor en uso** |
| `GEMINI_API_KEY` | Historial de `.env` | Ya rotada (el valor actual no aparece en el historial) |

No aparecen en el historial: `MERCADOPAGO_PUBLIC_KEY`, `MERCADOPAGO_ACCESS_TOKEN`, `GOOGLE_CLIENT_ID`, `MISTRAL_API_KEY`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`.

Con la `SECRET_KEY` un atacante puede firmar sesiones y cookies válidas y falsificar tokens de restablecimiento de contraseña de cualquier usuario; con las credenciales de MySQL, si el puerto es alcanzable, puede leer o modificar la base de datos completa. Qué hacer, en este orden: (1) rotar `SECRET_KEY` (esto invalida todas las sesiones activas, que es lo deseable), la contraseña de MySQL y las claves de ConvertAPI, Twelve Data, Alpha Vantage y currencyapi; (2) sacar `debug.log` del control de versiones (`git rm --cached debug.log`) y añadirlo a `.gitignore`; (3) reescribir el historial para eliminar `.env` y `debug.log` de todos los commits con `git filter-repo` (o BFG Repo-Cleaner) y forzar el push de todas las ramas, entendiendo que los forks o clones existentes conservarán el historial viejo, razón por la cual la rotación del paso 1 es imprescindible aunque se reescriba el historial; (4) activar en GitHub *Secret scanning* y *Push protection* para el repositorio; (5) evitar que las claves viajen en la query string de las URLs que se registran en logs (currencyapi las acepta en la cabecera `apikey`), o configurar el logger para no volcar URLs completas.

### 3.2 `tailwind==3.1.5b0` es el paquete equivocado y falta `django-tailwind` (alto)

`config/settings.py` incluye `'tailwind'` en `INSTALLED_APPS`, que es la app que provee el paquete `django-tailwind` (instalado en el entorno: 4.5.0, la última versión, pero **ausente de `requirements.txt`**). En su lugar `requirements.txt` fija `tailwind==3.1.5b0`, un paquete de PyPI de otro autor ("Python wrapper for Tailwind CSS v3.1.5", única versión publicada, beta de julio de 2022) que instala `tailwind/__init__.py`, `tailwind/__main__.py`, el ejecutable `tailwind/bin/tailwindcss-windows-x64.exe` (37 MB) y un `Scripts/tailwindcss.exe`. Los dos paquetes se pisan dentro de `site-packages/tailwind/`: hoy `__init__.py` es el de `django-tailwind` porque se instaló después, pero desinstalar cualquiera de los dos rompería al otro, y un `pip install -r requirements.txt` limpio (por ejemplo en Docker o en un servidor nuevo) instalaría solo el paquete equivocado y la aplicación no arrancaría, o cargaría código de un tercero no auditado que además incluye un binario precompilado. También está instalado `pytailwindcss 0.3.1` (otro envoltorio del binario standalone) sin estar fijado. Recomendación: quitar `tailwind==3.1.5b0` (y `pytailwindcss` si no se usa), añadir `django-tailwind==4.5.0`, recrear el entorno virtual desde cero y verificar que `python manage.py check` y `python manage.py tailwind build` funcionan.

### 3.3 Herramientas de desarrollo dentro de las dependencias de producción (medio)

`safety==3.8.1` (escáner de vulnerabilidades) está en `requirements.txt` con todo su árbol: `nltk` (30 avisos, 3 críticos, uno aún sin parche), `dparse`, `safety-schemas`, `typer`, `rich`, `ruamel.yaml`, `tomlkit`, `truststore`, `shellingham`, `joblib`, `regex`, `tqdm`, `marshmallow`, `pydantic`… Nada de esto lo importa la aplicación. Mover `safety` (y `pip-audit` si se adopta) a un `requirements-dev.txt` elimina de golpe el 40 % de los avisos de este informe y reduce la superficie de ataque del despliegue.

### 3.4 Otras observaciones de higiene

`virtual-enviroment/` no está en `.gitignore` (no está versionado hoy, pero basta un `git add .` descuidado); `staticfiles/` (642 archivos generados por `collectstatic`) sí está versionado y no debería; `.gemini/` (4 archivos de configuración de un asistente) también está versionado. `settings.py` no define `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` ni `SECURE_HSTS_SECONDS`, de modo que en producción las cookies de sesión y CSRF pueden viajar por HTTP; conviene activarlos condicionados a `not DEBUG`. El `.env` local tiene `DEBUG=True`, correcto en desarrollo siempre que el de producción sea distinto. `django-session-timeout==0.1.0` es la única versión del paquete y data de marzo de 2020: no tiene vulnerabilidades registradas, pero está sin mantenimiento; Django ya ofrece `SESSION_COOKIE_AGE` y `SESSION_SAVE_EVERY_REQUEST` para lo mismo. `alpha_vantage` no se importa en ningún archivo del proyecto y arrastra `aiohttp`; si no se usa, eliminarlo quita 11 avisos. No se encontraron secretos escritos directamente en el código fuente: todos se leen con `os.getenv`.

## 4. Vulnerabilidades en dependencias Python


| Paquete | Instalada | Avisos | Severidad máx. | Corregido desde | Última versión | Cómo llega al proyecto |
|---|---|---|---|---|---|---|
| `nltk` | 3.9.4 | 30 (1 sin parche) | Crítica (3) | 3.10.3 | 3.10.3 | No la usa la app: la arrastra `safety` (herramienta de auditoría) |
| `anyio` | 4.12.0 | 2 | Crítica (1) | 4.14.2 | 4.15.1 | Transitiva: `httpx`/`httpcore` (SDK de Mistral) |
| `pillow` | 12.2.0 | 13 | Alta (10) | 12.3.0 | 12.3.0 | Directa (procesa imágenes de comprobantes) |
| `aiohttp` | 3.14.0 | 11 | Alta (1) | 3.14.3 | 3.14.3 | Transitiva: solo `alpha_vantage` (no se importa en el código) |
| `sqlparse` | 0.5.5 | 5 | Alta (3) | 0.6.0 | 0.6.0 | Transitiva: `Django` |
| `cryptography` | 48.0.0 | 4 | Alta (3) | 50.0.0 | 50.0.1 | Transitiva: `django-allauth`, `PyJWT`, `Authlib` (OAuth/Google) |
| `pyasn1` | 0.6.3 | 3 | Alta (3) | 0.6.4 | 0.6.4 | Transitiva: `rsa` / `google-auth` |
| `httplib2` | 0.22.0 | 1 | Alta (1) | 0.32.0 | 0.32.0 | Transitiva: `google-api-python-client` (Google Drive) |
| `Django` | 6.0.6 | 4 | Media (3) | 6.0.8 | 6.1.1 | Directa (framework) |
| `setuptools` | 80.9.0 | 1 | Media (1) | 83.0.0 | 84.0.0 | Herramienta de build |
| `idna` | 3.10 | 1 | Media (1) | 3.15 | 3.20.0 | Transitiva: `requests` |
| `click` | 8.2.1 | 1 | Baja (1) | 8.3.3 | 8.5.0 | Transitiva: `celery` |


Lectura por relevancia para esta aplicación:

- **`pillow` 12.2.0 (13 avisos, 10 altos).** Es la más relevante en la práctica: la app abre imágenes de comprobantes que suben usuarios o llegan desde Google Drive, es decir, contenido controlado por terceros. Los avisos incluyen escrituras fuera de límites en heap (`Image.paste`/`Image.crop`, `ImageFilter.RankFilter`, `ImageCmsTransform`), varias evasiones de la protección contra bombas de descompresión (fuentes BDF/PCF, GD, PDF) y bucles infinitos (EPS). Todo se corrige en 12.3.0, que es además la última versión.
- **`anyio` 4.12.0 (1 crítico).** CVE-2026-63374: la codificación IDNA 2003 del nombre de host en `TLSStream` permite suplantar certificados TLS. Lo usa `httpx`, que es el cliente con el que el SDK de Mistral llama a su API. Corregido en 4.14.2 (última: 4.15.1).
- **`cryptography` 48.0.0 (3 altos).** Incluye un OpenSSL vulnerable en las ruedas (corregido en 48.0.1), un oráculo Bleichenbacher en PKCS#7 y un problema de construcción de cadenas de certificados. Sostiene el flujo OAuth con Google (`django-allauth`, `PyJWT`, `Authlib`). Corregido por completo en 50.0.0 (última: 50.0.1).
- **`Django` 6.0.6 (4 avisos, 3 medios).** Inyección de cabeceras vía `DomainNameValidator` (CVE-2026-53878), exposición de respuestas privadas por el middleware de caché (CVE-2026-48588), y dos problemas de GeoDjango que no aplican si no se usa `django.contrib.gis` (CVE-2026-53877, CVE-2026-15830). Todo corregido en 6.0.8, la última de la rama 6.0 (la última general es 6.1.1).
- **`sqlparse` 0.5.5 (3 altos)**, dependencia de Django: varias denegaciones de servicio por complejidad cuadrática/ReDoS al parsear SQL. Django solo lo usa en comandos de administración y en la introspección, así que la exposición desde peticiones web es baja; aun así 0.6.0 corrige todo.
- **`aiohttp` 3.14.0 (11 avisos)**: solo lo requiere `alpha_vantage`, que no se importa en ningún archivo del proyecto. La opción más limpia es eliminar `alpha_vantage`; si se conserva, subir `aiohttp` a 3.14.3.
- **`httplib2` 0.22.0, `pyasn1` 0.6.3, `idna` 3.10**: denegaciones de servicio en el cliente HTTP de Google Drive, en el decodificador ASN.1 usado por `google-auth`/`rsa` y en `requests`. Riesgo bajo-medio (haría falta un servidor o entrada maliciosa), corrección trivial.
- **`setuptools` 80.9.0 y `click` 8.2.1**: afectan a herramientas de build y a un uso local de `click.edit()`; riesgo bajo en producción.
- **`nltk` 3.9.4 (30 avisos, 3 críticos: RCE por deserialización pickle y por inyección de argumentos JVM)**: como se explicó en 3.3, no lo usa la aplicación; basta sacar `safety` del `requirements.txt` de producción. Si se mantiene, hay que subirlo a 3.10.3 sabiendo que CVE-2026-81726 aún no tiene parche.

## 5. Vulnerabilidades en dependencias npm (Tailwind/PostCSS, solo build)


| Paquete | Instalada | Avisos | Severidad máx. | Corregido desde | Última versión | Lo requiere |
|---|---|---|---|---|---|---|
| `tar` | 7.4.3 | 12 | Crítica (1) | 7.5.21 | 7.5.22 | `@tailwindcss/oxide` |
| `postcss` | 8.5.6 | 4 | Alta (2) | 8.5.23 | 8.5.28 | directa + `@tailwindcss/postcss` |
| `nanoid` | 3.3.11 | 3 | Alta (3) | 3.3.18 | 3.3.19 (rama 3.x) / 6.0.1 | `postcss` |
| `minimatch` | 10.0.3 | 3 | Alta (3) | 10.2.3 | 10.2.6 | `glob` ← `rimraf` |
| `picomatch` | 4.0.2 | 2 | Alta (1) | 4.0.4 | 4.0.7 | `anymatch`, `readdirp`, `tinyglobby` (chokidar/tailwind) |
| `picomatch` | 2.3.1 | 2 | Alta (1) | 2.3.2 | 4.0.7 | `anymatch`, `readdirp`, `tinyglobby` (chokidar/tailwind) |
| `@isaacs/brace-expansion` | 5.0.0 | 1 | Alta (1) | 5.0.1 | 5.0.1 | `minimatch` |
| `glob` | 11.0.3 | 1 | Alta (1) | 11.1.0 | 13.0.6 | `rimraf` |
| `yaml` | 2.8.0 | 1 | Media (1) | 2.8.3 | 2.9.1 | `postcss-load-config` ← `postcss-cli` |
| `postcss-selector-parser` | 7.1.0 | 1 | Baja (1) | 7.1.3 | 7.1.6 | `postcss-nested` |


Los 133 paquetes npm son `devDependencies` del tema de Tailwind: se ejecutan solo al compilar `styles.css` y no forman parte del código que se sirve al navegador ni del servidor Django. Por eso su riesgo real es para la máquina de desarrollo o el pipeline de build (un `tar` malicioso durante la instalación de `@tailwindcss/oxide`, ReDoS en patrones de `minimatch`/`picomatch`, lectura de archivos vía `sourceMappingURL` en `postcss`), no para los usuarios de la aplicación. Se corrigen casi por completo actualizando las ocho dependencias directas a sus versiones actuales y regenerando el lockfile: `tailwindcss` y `@tailwindcss/postcss` 4.3.3 (arrastran `tar` 7.5.22), `postcss` 8.5.28 (arrastra `nanoid` 3.3.19), `postcss-cli` 12.0.0 (arrastra `yaml` 2.9.x y `picomatch` 4.0.7), `rimraf` 6.1.3 (arrastra `glob` 13 / `minimatch` 10.2.6 / `@isaacs/brace-expansion` 5.0.1) y `postcss-nested` (arrastra `postcss-selector-parser` 7.1.6). `npm audit fix` en `theme/static_src` debería resolver todo sin cambios mayores salvo `postcss-cli` 11→12; conviene recompilar el CSS y comparar el resultado.

## 6. Plan de remediación propuesto (por prioridad)

**Prioridad 0 — hoy (secretos).** Rotar `SECRET_KEY`, contraseña de MySQL, `CONVERT_API_KEY`, `TWELVEDATA_API_KEY`, `ALPHA_VANTAGE_API_KEY` y `CURRENCYAPI_API_KEY`; `git rm --cached debug.log` y añadir `debug.log`, `virtual-enviroment/` y `staticfiles/` a `.gitignore`; purgar `.env` y `debug.log` del historial con `git filter-repo` y `git push --force --all`; activar *Secret scanning* + *Push protection* en GitHub. Si el servidor MySQL de producción está expuesto a Internet, restringirlo por firewall además de cambiar la contraseña.

**Prioridad 1 — esta semana (runtime con entrada de terceros).** `pillow` → 12.3.0; `anyio` → 4.15.1; `cryptography` → 50.0.1; `Django` → 6.0.8; sustituir `tailwind==3.1.5b0` por `django-tailwind==4.5.0` y recrear el entorno virtual limpio. Probar el flujo completo: login con Google, subida/lectura de comprobantes (Gemini y Mistral), tareas Celery.

**Prioridad 2 — próximo sprint.** `sqlparse` 0.6.0, `pyasn1` 0.6.4, `httplib2` 0.32.0, `idna` 3.20.0, `setuptools` 84.0.0, `click` 8.5.0; eliminar `alpha_vantage` (o subir `aiohttp` a 3.14.3); mover `safety` y su árbol a `requirements-dev.txt`; `npm audit fix` en `theme/static_src`; activar `SECURE_SSL_REDIRECT`, `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` y `SECURE_HSTS_SECONDS` cuando `DEBUG` sea `False`.

**Prioridad 3 — continuo.** Dependabot para `pip` y `npm` (archivo `.github/dependabot.yml`), `pip-audit` y `npm audit` en CI, y un hook de pre-commit con `gitleaks` para que ningún secreto vuelva a entrar en un commit.

### 6.1 Cambios propuestos en `requirements.txt` (sin aplicar)

```diff
-Django==6.0.6
+Django==6.0.8
-pillow==12.2.0
+pillow==12.3.0
-anyio==4.12.0
+anyio==4.15.1
-cryptography==48.0.0
+cryptography==50.0.1
-sqlparse==0.5.5
+sqlparse==0.6.0
-pyasn1==0.6.3
+pyasn1==0.6.4
-httplib2==0.22.0
+httplib2==0.32.0
-idna==3.10
+idna==3.20.0
-setuptools==80.9.0
+setuptools==84.0.0
-click==8.2.1
+click==8.5.0
-tailwind==3.1.5b0
+django-tailwind==4.5.0
-alpha_vantage==3.0.0        # no se importa en el proyecto; si se conserva: aiohttp==3.14.3
-aiohttp==3.14.0
-safety==3.8.1               # → requirements-dev.txt (junto con nltk, dparse, safety-schemas, typer, rich, …)
```

Las versiones propuestas son las últimas publicadas a fecha de hoy y respetan las restricciones declaradas por los paquetes que dependen de ellas (`pyasn1_modules` exige `pyasn1<0.7`, `google-api-python-client` exige `httplib2<1.0`, `celery` exige `click<9`). Aun así, `cryptography` 48→50 y `click` 8.2→8.5 son saltos de versión mayor/menor y merecen pasar la suite de pruebas antes de desplegar. Tras aplicar los cambios, regenerar el entorno con `pip install -r requirements.txt` desde cero y verificar con `pip-audit -r requirements.txt`.

## 7. Cómo repetir este escaneo

En la máquina de desarrollo, con el entorno virtual activo: `pip install pip-audit && pip-audit -r requirements.txt --desc` para Python, y `cd theme/static_src && npm audit` para npm. Para un SBOM en formato CycloneDX que se pueda entregar o archivar: `pip install cyclonedx-bom && cyclonedx-py requirements requirements.txt -o sbom-python.json` y `npx @cyclonedx/cyclonedx-npm --output-file sbom-npm.json` dentro de `theme/static_src`. Para buscar secretos en todo el historial: instalar el binario de gitleaks (no es un paquete de PyPI) y ejecutar `gitleaks git --redact` en la raíz del repositorio.


## Apéndice A – Avisos Python por paquete (versión instalada)

**nltk 3.9.4**

- GHSA-m4rf-3fr8-xwx3 / CVE-2026-79675 — Crítica, CVSS 9.8 — corregido en 3.10.3 — NLTK: JVM argument injection bypass via per-call options in the NLTK Stanford wrappers (incomplete fix of CVE-2026-12841)
- GHSA-x99w-6fgc-pmfw / CVE-2026-79657 — Crítica — corregido en 3.10.3 — NLTK: Allowlisted pickle loaders still permit code execution in current source
- GHSA-rhp5-r9x4-f5g2 / CVE-2026-78683 — Crítica — corregido en 3.10.0 — NLTK: Unsafe Pickle Deserialization in TransitionParser Allows Remote Code Execution
- GHSA-p4gq-832x-fm9v / CVE-2026-54293 — Alta, CVSS 7.5 — corregido en 3.10.0 — Natural Language Toolkit (NLTK): URL-Encoded Path Traversal in nltk.data.load() Allows Arbitrary Local File Read
- GHSA-qvv7-cg9c-w4x3 / CVE-2026-12075 — Alta, CVSS 8.6 — corregido en 3.10.0 — Natural Language Toolkit (NLTK): DNS-rebinding SSRF filter bypass in nltk.pathsec.urlopen (nltk.download / nltk.data.load) defeats ENFORCE mode
- GHSA-fg7f-2386-8897 / CVE-2026-12061 — Alta, CVSS 7.5 — corregido en 3.10.0 — Natural Language Toolkit (NLTK): ReDoS in NLTK ReviewsCorpusReader FEATURES regex
- GHSA-6hm5-jgcp-p838 / CVE-2026-12072 — Alta, CVSS 7.5 — corregido en 3.10.0 — Natural Language Toolkit (NLTK): Path Traversal in NKJPCorpusReader leads to Arbitrary File Read and bypasses the nltk.pathsec sandbox (ENFORCE=True)
- GHSA-xh95-f55m-82fw / CVE-2026-12074 — Alta, CVSS 7.5 — corregido en 3.10.0 — Natural Language Toolkit (NLTK) has path traversal in FramenetCorpusReader.frame() that allows arbitrary XML file read, bypassing the nltk.pathsec sandbox (ENFORCE=True)
- GHSA-m42h-3232-vpv3 / CVE-2026-12243 — Alta, CVSS 7.5 — corregido en 3.10.0 — nltk: Arbitrary File Read via Path Traversal in nltk.data.load() through Percent-Encoded Sequences
- GHSA-qx2g-xrx7-vfh8 / CVE-2026-72818 — Alta, CVSS 7.5 — corregido en 3.10.1 — NLTK TweetTokenizer vulnerable to denial of service through catastrophic regex backtracking
- GHSA-6hwm-xvph-95vm / CVE-2026-78680 — Alta, CVSS 7.8 — corregido en 3.10.3 — NLTK: Uncontrolled search path when invoking the Graphviz 'dot' binary
- GHSA-p3m8-78j2-g5p3 / CVE-2026-62388 — Alta — corregido en 3.10.0 — NLTK: Default ENFORCE=False Disables All pathsec Security Controls
- GHSA-8mgp-746c-j5xp / CVE-2026-81726 — Alta, CVSS 7.0 — sin versión corregida publicada — NLTK: Model-artifact APIs bypass pathsec and touch files outside allowed roots
- GHSA-w3v8-gmh9-3wv7 / CVE-2026-80206 — Alta — corregido en 3.10.3 — NLTK: ReDoS in nltk.tgrep via unvalidated user-supplied regular expressions
- GHSA-rrv8-h7p8-rx55 / CVE-2026-80205 — Alta, CVSS 7.5 — corregido en 3.10.0 — NLTK: ReDoS in nltk.text.Text.findall() via unvalidated user-supplied regular expressions
- GHSA-3gq4-3j92-5w49 / CVE-2026-79674 — Alta — corregido en 3.10.3 — NLTK: Corpus Reader Sandbox Bypass
- GHSA-p4rw-rvv2-7xwr / CVE-2026-79676 — Alta — corregido en 3.10.3 — NLTK: Corpus readers follow symlinks outside trusted roots despite pathsec enforcement
- GHSA-97qj-x29f-37w7 / CVE-2026-78681 — Alta — corregido en 3.10.3 — NLTK: Entity-expansion DoS (billion laughs) via remaining raw ElementTree parses
- GHSA-6ww7-3frv-cqxh / CVE-2026-78682 — Alta — corregido en 3.10.3 — NLTK: pathsec SSRF protection can be bypassed when a proxy is configured
- GHSA-568f-pv23-39p4 / CVE-2026-62385 — Alta, CVSS 5.9 — corregido en 3.10.0 — NLTK: Stable FrameNet and NKJP readers parse outside-root XML
- GHSA-x5ph-mj9p-rfr8 / CVE-2026-63312 — Alta — corregido en 3.10.0 — NLTK: StreamBackedCorpusView Bypasses pathsec.ENFORCE - Arbitrary Local File Read
- GHSA-3gqm-fcw5-w839 / CVE-2026-63311 — Media — corregido en 3.10.0 — NLTK: SSRF Fail-Open in validate_network_url() via DNS Resolution Failure
- GHSA-ww6m-cw3f-q94g / CVE-2026-81722 — Media — corregido en 3.10.3 — NLTK: Quadratic-time DoS in PorterStemmer via long runs of 'y'
- GHSA-f794-5jv7-7672 / CVE-2026-81727 — Media, CVSS 7.1 — corregido en 3.10.3 — NLTK: Downloader.download follows hardlinks and overwrites outside-root files
- GHSA-vp2x-qp44-57v7 / CVE-2026-81723 — Media, CVSS 3.7 — corregido en 3.10.3 — NLTK: Quadratic CPU Exhaustion in `XMLCorpusView._read_xml_fragment()`
- GHSA-ff5c-cp5c-9wjf / CVE-2026-12876 — Media — corregido en 3.10.3 — NLTK: Uncontrolled resource consumption in RecursiveDescentParser via ambiguous or left-recursive grammars
- GHSA-cw6x-m8jw-qmrh / CVE-2026-81724 — Media, CVSS 5.3 — corregido en 3.10.3 — NLTK: Uncontrolled recursion in nltk.featstruct.FeatStructReader causes unhandled RecursionError (DoS) via deeply nested feature-structure input
- GHSA-8mpw-7fpc-4gqj / CVE-2026-81725 — Media — corregido en 3.10.3 — NLTK: Pl196xCorpusReader has quadratic ReDoS on malformed TEI blocks
- GHSA-72r2-7mfr-5xr9 / CVE-2026-65915 — Media — corregido en 3.10.0 — NLTK: FileSystemPathPointer.open() sandbox check is dead code — arbitrary file read via file://
- GHSA-cv22-g7mw-8v73 / CVE-2026-71514 — Baja, CVSS 2.5 — corregido en 3.10.3 — NLTK CrubadanCorpusReader path traversal allows arbitrary file disclosure

**anyio 4.12.0**

- GHSA-82r6-8w77-94w6 / CVE-2026-63374 — Crítica — corregido en 4.14.2 — AnyIO: TLSStream IDNA 2003 host name encoding enables potential TLS certificate spoofing
- GHSA-5p39-cfhj-2xmp / CVE-2026-64847 — Media — corregido en 4.14.2 — AnyIO process-pool workers can block indefinitely on undrained stderr

**pillow 12.2.0**

- GHSA-9hw9-ch79-4vh6 / CVE-2026-59205 — Alta, CVSS 7.5 — corregido en 12.3.0 — Pillow: Controlled heap out-of-bounds write in Pillow `ImageCmsTransform.apply()` via output mode mismatch
- GHSA-vjc4-5qp5-m44j / CVE-2026-59204 — Alta — corregido en 12.3.0 — Pillow JPEG2000 tiled decode retains a growing scratch buffer and can be used for denial of service
- GHSA-phj9-mv4w-65pm / CVE-2026-55380 — Alta, CVSS 7.5 — corregido en 12.3.0 — Pillow `GdImageFile._open()`: image dimensions accepted without `_decompression_bomb_check()`
- GHSA-45hq-cxwh-f6vc / CVE-2026-55379 — Alta, CVSS 7.5 — corregido en 12.3.0 — Pillow `BdfFontFile`: `Image.new()` called without `_decompression_bomb_check()` — bomb protection bypass via font loading
- GHSA-5x94-69rx-g8h2 / CVE-2026-54060 — Alta, CVSS 7.5 — corregido en 12.3.0 — Pillow: `FontFile.compile()`: `Image.new()` called without `_decompression_bomb_check()`
- GHSA-8v84-f9pq-wr9x / CVE-2026-54059 — Alta, CVSS 7.5 — corregido en 12.3.0 — Pillow `PcfFontFile._load_bitmaps()`: `Image.frombytes()` called without `_decompression_bomb_check()` — bomb protection bypass via PCF font loading
- GHSA-62p4-gmf7-7g93 / CVE-2026-54058 — Alta — corregido en 12.3.0 — Pillow: Out-of-bounds read via attacker-controlled row stride on Pillow's mmap path (McIdas AREA files)
- GHSA-6r8x-57c9-28j4 / CVE-2026-59199 — Alta — corregido en 12.3.0 — Pillow: heap OOB write in Image.paste()/Image.crop() via signed coordinate overflow
- GHSA-jjj6-mw9f-p565 / CVE-2026-59200 — Alta — corregido en 12.3.0 — Pillow: decompression bomb DoS via PdfParser.PdfStream.decode()
- GHSA-xj96-63gp-2gmr / CVE-2026-59197 — Alta — corregido en 12.3.0 — Pillow: heap OOB write in ImageFilter.RankFilter via integer overflow
- GHSA-pg7v-jwj7-p798 / CVE-2026-59203 — Media, CVSS 5.3 — corregido en 12.3.0 — Pillow EpsImagePlugin negative %%BeginBinary byte count causes infinite loop denial of service
- GHSA-4x4j-2g7c-83w6 / CVE-2026-55798 — Media — corregido en 12.3.0 — Pillow: WindowsViewer.get_command() OS command injection via unescaped shell path
- GHSA-fj7v-r99m-22gq / CVE-2026-59198 — Media — corregido en 12.3.0 — Pillow: TGA RLE encoder leaks up to ~57 KB of heap data into generated images

**aiohttp 3.14.0**

- GHSA-cq5v-8q36-5273 / CVE-2026-69244 — Alta — corregido en 3.14.3 — AIOHTTP: Out-of-bounds heap read in C HTTP response parser error path (malformed chunked response)
- GHSA-xcgm-r5h9-7989 / CVE-2026-54274 — Media — corregido en 3.14.1 — aiohttp: Incomplete websocket frame payloads bypass memory limits
- GHSA-4fvr-rgm6-gqmc / CVE-2026-54273 — Media — corregido en 3.14.1 — aiohttp: HTTP/1 Pipelined Requests Queue Without Limit
- GHSA-g3cq-j2xw-wf74 / CVE-2026-54278 — Media — corregido en 3.14.1 — aiohttp: Unread Compressed Request Bodies Bypass client_max_size During Cleanup
- GHSA-63hw-fmq6-xxg2 / CVE-2026-54277 — Media — corregido en 3.14.1 — aiohttp: C HTTP Parser Bypasses max_line_size for Fragmented Lines
- GHSA-hpj7-wq8m-9hgp / CVE-2026-54276 — Media — corregido en 3.14.1 — aiohttp: DigestAuthMiddleware Applies Credentials to Cross-Origin Redirect Challenges
- GHSA-mfx4-hv73-q22v / CVE-2026-69243 — Media — corregido en 3.14.2 — AIOHTTP: HTTP request smuggling via WebSocket upgrade
- GHSA-mq44-7p77-q5h7 / CVE-2026-59881 — Media — corregido en 3.14.2 — AIOHTTP: WebSocket client accepts compressed frames without negotiated permessage-deflate
- GHSA-4m7w-qmgq-4wj5 / CVE-2026-54275 — Baja — corregido en 3.14.1 — aiohttp: TLS Server Hostname Override Is Ignored When Reusing HTTPS Connections
- GHSA-9x8q-7h8h-wcw9 / CVE-2026-54280 — Baja — corregido en 3.14.1 — aiohttp: Payload Response Resources Are Not Closed After Mid-Body Disconnect
- GHSA-2fqr-mr3j-6wp8 / CVE-2026-54279 — Baja — corregido en 3.14.1 — aiohttp: Host-Only Cookies Become Domain Cookies After CookieJar Persistence

**sqlparse 0.5.5**

- GHSA-prg7-hcfm-mfcr / CVE-2026-59893 — Alta, CVSS 7.5 — corregido en 0.6.0 — sqlparse: Inefficient Regex Handling of Dollar-Quoted SQL Literals Leads to ReDoS (Denial of Service)
- GHSA-pwgv-4x5q-6m9f / CVE-2026-54284 — Alta — corregido en 0.6.0 — sqlparse: TokenList.__init__ materializes O(subtree) value per group, causing CPU DoS before depth/token caps trigger
- GHSA-f2ff-p2ww-7p4p / CVE-2026-71491 — Alta — corregido en 0.6.0 — sqlparse: Quadratic O(n²) DoS in group_comments
- GHSA-3496-9g83-7v6x / CVE-2026-59894 — Media — corregido en 0.6.0 — sqlparse: Generated Python and PHP snippets allow SQL string breakout through unescaped backslashes
- GHSA-cfqr-cjx5-5jcm / CVE-2026-84305 — Media — corregido en 0.6.0 — sqlparse: Reindentation of tuple lists causes near-cap quadratic CPU consumption

**cryptography 48.0.0**

- GHSA-537c-gmf6-5ccf — Alta, CVSS 7.5 — corregido en 48.0.1 — Vulnerable OpenSSL included in cryptography wheels
- GHSA-jwv3-5hgf-82ww / CVE-2026-69249 — Alta — corregido en 49.0.0 — python-cryptography: Duplicate self-signed intermediates can cause exponential path-building
- GHSA-g6cj-pr64-35w5 / CVE-2026-69247 — Alta — corregido en 50.0.0 — cryptography: PKCS#7 EnvelopedData decryption exposes a Bleichenbacher oracle through distinguishable errors and timing
- GHSA-m2h6-j472-rp4c / CVE-2026-69248 — Media — corregido en 49.0.0 — python-cryptography verifier accepts wildcard DNS names allowing escape from permittedSubtrees

**pyasn1 0.6.3**

- GHSA-hm4w-wwcw-mr6r / CVE-2026-59886 — Alta, CVSS 7.5 — corregido en 0.6.4 — pyasn1: Uncontrolled resource consumption when converting decoded REAL values
- GHSA-8ppf-4f7h-5ppj / CVE-2026-59885 — Alta, CVSS 7.5 — corregido en 0.6.4 — pyasn1: Quadratic complexity in OBJECT IDENTIFIER and RELATIVE-OID processing allows denial of service
- GHSA-m4p7-r5rc-7g4j / CVE-2026-59884 — Alta, CVSS 7.5 — corregido en 0.6.4 — pyasn1 BER/CER/DER decoder denial of service via unbounded long-form tag IDs

**httplib2 0.22.0**

- GHSA-j5g9-f88f-gfj3 / CVE-2026-59939 — Alta, CVSS 7.5 — corregido en 0.32.0 — httplib2: Decompression Bomb Denial of Service via Unbounded gzip/deflate Response Handling

**Django 6.0.6**

- GHSA-crhf-3pfg-w68w / CVE-2026-53877 — Media, CVSS 4.8 — corregido en 6.0.7 — Django: GDALRaster may over-read heap memory when constructed from bytes
- GHSA-8qcx-xf44-272x / CVE-2026-53878 — Media, CVSS 6.1 — corregido en 6.0.7 — Django: DomainNameValidator permits newline characters that may enable HTTP header injection
- PYSEC-2026-3717 / CVE-2026-15830 — Media — corregido en 6.0.8 — Django: GeoDjango GEOSGeometry DoS via deeply nested GEOMETRYCOLLECTION (WKT/WKB)
- GHSA-3h9f-r86x-qvjx / CVE-2026-48588 — Baja, CVSS 3.1 — corregido en 6.0.7 — Django: cache middleware may expose private responses when unrelated request cookies are present

**setuptools 80.9.0**

- GHSA-h35f-9h28-mq5c / CVE-2026-59890 — Media, CVSS 6.1 — corregido en 83.0.0 — setuptools: MANIFEST.in exclusion bypass in sdist via Unicode normalization collision (NFC/NFD) on macOS APFS/HFS+

**idna 3.10**

- GHSA-65pc-fj4g-8rjx / CVE-2026-45409 — Media, CVSS 5.3 — corregido en 3.15 — Internationalized Domain Names in Applications (IDNA): Specially crafted inputs to idna.encode() can bypass CVE-2024-3651 fix

**click 8.2.1**

- GHSA-47fr-3ffg-hgmw / CVE-2026-7246 — Baja — corregido en 8.3.3 — Click: command injection in click.edit() (local, high complexity)

## Apéndice B – Avisos npm por paquete (versión instalada)

**tar@7.4.3**

- GHSA-23hp-3jrh-7fpw / CVE-2026-59873 — Crítica, CVSS 7.5 — corregido en 7.5.19 — node-tar: Decompression/parse DoS via unlimited input
- GHSA-8qq5-rm4j-mr97 / CVE-2026-23745 — Alta — corregido en 7.5.3 — node-tar is Vulnerable to Arbitrary File Overwrite and Symlink Poisoning via Insufficient Path Sanitization
- GHSA-r6q2-hw4h-h46w / CVE-2026-23950 — Alta, CVSS 8.8 — corregido en 7.5.4 — Race Condition in node-tar Path Reservations via Unicode Ligature Collisions on macOS APFS
- GHSA-34x7-hfp2-rc4v / CVE-2026-24842 — Alta, CVSS 8.2 — corregido en 7.5.7 — node-tar Vulnerable to Arbitrary File Creation/Overwrite via Hardlink Path Traversal
- GHSA-83g3-92jg-28cx / CVE-2026-26960 — Alta, CVSS 7.1 — corregido en 7.5.8 — Arbitrary File Read/Write via Hardlink Target Escape Through Symlink Chain in node-tar Extraction
- GHSA-qffp-2rhf-9h96 / CVE-2026-29786 — Alta — corregido en 7.5.10 — tar has Hardlink Path Traversal via Drive-Relative Linkpath
- GHSA-9ppj-qmqm-q256 / CVE-2026-31802 — Alta — corregido en 7.5.11 — node-tar Symlink Path Traversal via Drive-Relative Linkpath
- GHSA-8x88-c5mf-7j5w / CVE-2026-59874 — Alta, CVSS 7.5 — corregido en 7.5.18 — node-tar: Negative tar entry size causes infinite loop in archive replace
- GHSA-r292-9mhp-454m / CVE-2026-73566 — Alta, CVSS 7.5 — corregido en 7.5.21 — node-tar: Uncontrolled recursion in mapHas/filesFilter allows uncatchable stack-overflow DoS via crafted long-path tar with member selection
- GHSA-vmf3-w455-68vh / CVE-2026-53655 — Media — corregido en 7.5.16 — node-tar applies PAX size override to intermediary GNU long-name/long-link headers, causing tar parser interpretation differential (file smuggling)
- GHSA-w8wr-v893-vjvp / CVE-2026-59871 — Media, CVSS 5.3 — corregido en 7.5.18 — node-tar: Process crash via PAX numeric path type confusion
- GHSA-gvwx-54wh-qm9j / CVE-2026-59875 — Media, CVSS 5.3 — corregido en 7.5.17 — node-tar: Uncaught Exception DoS via NUL byte in PAX path/linkpath records

**postcss@8.5.6**

- GHSA-6g55-p6wh-862q / CVE-2026-45623 — Alta, CVSS 7.5 — corregido en 8.5.12 — PostCSS: Arbitrary file read and information disclosure via attacker-controlled sourceMappingURL in CSS comments
- GHSA-r28c-9q8g-f849 / CVE-2026-73646 — Alta, CVSS 7.5 — corregido en 8.5.18 — PostCSS: Path Traversal in Previous Source Map Auto-Loading (sourceMappingURL) leads to Arbitrary .map File Disclosure
- GHSA-qx2v-qp2m-jg93 / CVE-2026-41305 — Media, CVSS 6.1 — corregido en 8.5.10 — PostCSS has XSS via Unescaped </style> in its CSS Stringify Output
- GHSA-fxqj-rqcc-2cmp / CVE-2026-69153 — Media — corregido en 8.5.23 — PostCSS: incomplete fix of GHSA-6g55-p6wh-862q — attacker-controlled sourceMappingURL reads arbitrary .map files when `from` is unset

**nanoid@3.3.11**

- GHSA-28wg-ghj8-5hjv / CVE-2026-67214 — Alta, CVSS 5.9 — corregido en 3.3.16 — nanoid: non-secure generators can loop indefinitely with negative size
- GHSA-2v37-7h3g-55p8 / CVE-2026-67213 — Alta, CVSS 5.9 — corregido en 3.3.18 — nanoid: custom generators can loop indefinitely when size is zero
- GHSA-xwg4-73v4-xw9w / CVE-2026-73086 — Alta, CVSS 7.4 — corregido en 3.3.12 — nanoid: Integer Overflow or Wraparound

**minimatch@10.0.3**

- GHSA-3ppc-4f35-3m26 / CVE-2026-26996 — Alta — corregido en 10.2.1 — minimatch has a ReDoS via repeated wildcards with non-matching literal in pattern
- GHSA-7r86-cg39-jmmj / CVE-2026-27903 — Alta, CVSS 7.5 — corregido en 10.2.3 — minimatch has ReDoS: matchOne() combinatorial backtracking via multiple non-adjacent GLOBSTAR segments
- GHSA-23c5-xmqv-rm74 / CVE-2026-27904 — Alta, CVSS 7.5 — corregido en 10.2.3 — minimatch ReDoS: nested *() extglobs generate catastrophically backtracking regular expressions

**picomatch@4.0.2**

- GHSA-c2c7-rcm5-vvqj / CVE-2026-33671 — Alta, CVSS 7.5 — corregido en 4.0.4 — Picomatch has a ReDoS vulnerability via extglob quantifiers
- GHSA-3v7f-55p6-f55p / CVE-2026-33672 — Media, CVSS 5.3 — corregido en 4.0.4 — Picomatch: Method Injection in POSIX Character Classes causes incorrect Glob Matching

**picomatch@2.3.1**

- GHSA-c2c7-rcm5-vvqj / CVE-2026-33671 — Alta, CVSS 7.5 — corregido en 2.3.2 — Picomatch has a ReDoS vulnerability via extglob quantifiers
- GHSA-3v7f-55p6-f55p / CVE-2026-33672 — Media, CVSS 5.3 — corregido en 2.3.2 — Picomatch: Method Injection in POSIX Character Classes causes incorrect Glob Matching

**@isaacs/brace-expansion@5.0.0**

- GHSA-7h2j-956f-4vf2 / CVE-2026-25547 — Alta — corregido en 5.0.1 — @isaacs/brace-expansion has Uncontrolled Resource Consumption

**glob@11.0.3**

- GHSA-5j98-mcp5-4vw2 / CVE-2025-64756 — Alta, CVSS 7.5 — corregido en 11.1.0 — glob CLI: Command injection via -c/--cmd executes matches with shell:true

**yaml@2.8.0**

- GHSA-48c2-rrv3-qjmp / CVE-2026-33532 — Media, CVSS 4.3 — corregido en 2.8.3 — yaml is vulnerable to Stack Overflow via deeply nested YAML collections

**postcss-selector-parser@7.1.0**

- GHSA-w9m9-85wc-3x92 / CVE-2026-9358 — Baja, CVSS 4.3 — corregido en 7.1.3 — postcss-selector-parser allows denial of service through uncontrolled AST recursion

---
*Fuentes consultadas: GitHub Advisory Database (api.github.com/advisories, filtro `affects`), OSV.dev (api.osv.dev/v1/vulns) y deps.dev (api.deps.dev/v3) el 26 de septiembre de 2026. Los rangos afectados se verificaron con `packaging` (PyPI) y `semver` (npm) contra las versiones instaladas.*
