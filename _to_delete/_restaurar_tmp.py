"""Restaura 8 archivos desde HEAD y vuelve a aplicar solo los cambios puntuales entregados después."""
import subprocess, sys, os
ROOT = sys.argv[1]
CUENTAFORM = open(sys.argv[2], encoding='utf-8').read()
os.chdir(ROOT)

def head(path):
    return subprocess.run(['git', 'show', f'HEAD:{path}'], capture_output=True, text=True, encoding='utf-8', check=True).stdout

def aplicar(path, parches):
    s = head(path)
    for old, new in parches:
        if old not in s:
            print(f"  !! {path}: no encontré el ancla -> {old[:60]!r}; se queda la versión de HEAD en esa parte")
            continue
        s = s.replace(old, new, 1)
    open(path, 'w', encoding='utf-8', newline='\n').write(s)
    print(f"OK {path}")

# 1. tasks.py: reintento ante errores transitorios de Gemini
aplicar('finanzas/tasks.py', [
    ("from celery import shared_task, group\n", "from celery import shared_task, group\nfrom celery.exceptions import Retry\n"),
    ("""        if extracted_data.get("error"):
             return {'status': 'FAILURE', 'file_name': file_name, 'error': extracted_data.get('raw_response', 'Error desconocido')}

        TransactionService().create_pending_transaction(user, extracted_data)
        return {'status': 'SUCCESS', 'file_name': file_name}
    except Exception as e:
        self.retry(exc=e)
        return {'status': 'FAILURE', 'file_name': file_name, 'error': str(e)}""",
     """        if extracted_data.get("error"):
            if extracted_data.get("transitorio") and self.request.retries < self.max_retries:
                # La API estuvo lenta/saturada: lo volvemos a intentar en un minuto en vez de darlo por perdido.
                raise self.retry(countdown=60)
            return {'status': 'FAILURE', 'file_name': file_name,
                    'error': extracted_data.get('raw_response') or extracted_data.get('error') or 'Error desconocido'}

        TransactionService().create_pending_transaction(user, extracted_data)
        return {'status': 'SUCCESS', 'file_name': file_name}
    except Retry:
        raise
    except Exception as e:
        self.retry(exc=e)
        return {'status': 'FAILURE', 'file_name': file_name, 'error': str(e)}"""),
])

# 2. ai_service.py: timeout 120 s + reintentos
aplicar('finanzas/services/ai_service.py', [
    ("import os\nimport json\n", "import os\nimport json\nimport time\n"),
    ("""    def _generate_and_parse(self, prompt: str, content) -> dict:
        inputs = [prompt, content] if content else prompt
        try:
            # ponytail: timeout duro para que un cuelgue de la API no deje el request colgado
            response = self.model.generate_content(
                inputs, safety_settings=self.safety_settings,
                request_options={"timeout": 30}
            )
            # Since response_mime_type="application/json", response.text is guaranteed valid JSON
            return json.loads(response.text)
        except Exception as e:
            logger.error(f"Gemini API Error: {e}")
            return {"error": str(e)}""",
     """    # Errores de la API que vale la pena reintentar (lentitud o saturación, no un fallo del contenido)
    ERRORES_TRANSITORIOS = ('504', '503', '429', 'Deadline', 'Unavailable', 'ResourceExhausted', 'timed out', 'timeout')

    @classmethod
    def es_transitorio(cls, error) -> bool:
        return any(t.lower() in str(error).lower() for t in cls.ERRORES_TRANSITORIOS)

    def _generate_and_parse(self, prompt: str, content) -> dict:
        inputs = [prompt, content] if content else prompt
        ultimo_error = None
        for intento in range(3):
            try:
                # Las imágenes tardan: 120 s de tope por llamada, y dos reintentos si la API está lenta.
                response = self.model.generate_content(
                    inputs, safety_settings=self.safety_settings,
                    request_options={"timeout": 120}
                )
                # Since response_mime_type="application/json", response.text is guaranteed valid JSON
                return json.loads(response.text)
            except Exception as e:
                ultimo_error = e
                if not self.es_transitorio(e) or intento == 2:
                    break
                espera = 10 * (intento + 1)
                logger.warning(f"Gemini lento o saturado ({e}); reintento {intento + 1}/2 en {espera}s")
                time.sleep(espera)
        logger.error(f"Gemini API Error: {ultimo_error}")
        return {"error": str(ultimo_error), "transitorio": self.es_transitorio(ultimo_error)}"""),
])

# 3. forms.py: CuentaForm (sin préstamos en el tipo; saldo inicial editable)
s = head('finanzas/forms.py')
i0, i1 = s.index('class CuentaForm'), s.index('class TransaccionesForm')
s = s[:i0] + CUENTAFORM + s[i1:]
open('finanzas/forms.py', 'w', encoding='utf-8', newline='\n').write(s); print('OK finanzas/forms.py')

# 4. views/cuentas.py: Mis Tarjetas sin préstamos
aplicar('finanzas/views/cuentas.py', [
    ("    cuentas = Cuenta.objects.filter(propietario=request.user).order_by('-es_principal', 'tipo', 'nombre')\n",
     "    # Los préstamos tienen cuenta en el libro, pero se administran en Deudas, no aquí.\n    cuentas = Cuenta.objects.filter(propietario=request.user).exclude(tipo='PRESTAMO').order_by('-es_principal', 'tipo', 'nombre')\n"),
])

# 5. editar_cuenta.html: campo saldo inicial antes de saldo actual
s = head('finanzas/templates/editar_cuenta.html')
lineas = s.split('\n')
idx = next(i for i, l in enumerate(lineas) if 'form.saldo_actual.label' in l)
div_idx = max(i for i in range(idx) if '<div class="mt-4">' in lineas[i])
bloque = '''                <div class="mt-4">
                    <label class="block text-sm font-medium text-gray-700 mb-1">{{ form.saldo_inicial.label }}</label>
                    {{ form.saldo_inicial }}
                    <p class="mt-1 text-xs text-gray-400">{{ form.saldo_inicial.help_text }}</p>
                    {% for error in form.saldo_inicial.errors %}<p class="mt-1 text-xs text-red-600">{{ error }}</p>{% endfor %}
                </div>
'''
lineas.insert(div_idx, bloque.rstrip('\n'))
open('finanzas/templates/editar_cuenta.html', 'w', encoding='utf-8', newline='\n').write('\n'.join(lineas)); print('OK finanzas/templates/editar_cuenta.html')

# 6. resumen.html: enlace "ajustar saldo inicial" en la conciliación
aplicar('finanzas/templates/resumen.html', [
    ("""                        <td class="px-6 py-3 font-medium text-gray-900">{{ c.cuenta.nombre }} <span class="text-[11px] text-gray-400">· {{ c.cuenta.get_tipo_display }}</span></td>""",
     """                        <td class="px-6 py-3 font-medium text-gray-900">{{ c.cuenta.nombre }} <span class="text-[11px] text-gray-400">· {{ c.cuenta.get_tipo_display }}</span>
                            <a href="{% if c.cuenta.tipo == 'PRESTAMO' and c.cuenta.deuda %}{% url 'editar_deuda' c.cuenta.deuda.id %}{% else %}{% url 'editar_cuenta' c.cuenta.id %}{% endif %}"
                               class="block text-[11px] text-indigo-600 hover:underline mt-0.5">ajustar saldo inicial (hoy: {{ c.cuenta.saldo_inicial|dinero }})</a>
                        </td>"""),
])

# 7. dashboard_charts.js: tooltips en pesos
s = head('finanzas/static/js/dashboard_charts.js')
helper = '''// Formato de pesos para etiquetas y tooltips: $1,450.00
const formatoPesos = new Intl.NumberFormat('es-MX', { style: 'currency', currency: 'MXN', minimumFractionDigits: 2 });
function pesos(valor) { return formatoPesos.format(Number(valor) || 0); }

'''
s = helper + s
old = """                            legend: {
                                position: 'bottom',
                                labels: { boxWidth: 12, padding: 10, font: { size: 11 } }
                            }
                        }"""
new = """                            legend: {
                                position: 'bottom',
                                labels: { boxWidth: 12, padding: 10, font: { size: 11 } }
                            },
                            tooltip: {
                                callbacks: {
                                    // "Carro: $1,450.00 (41%)"
                                    label: function (ctx) {
                                        const total = ctx.dataset.data.reduce((a, b) => a + Number(b), 0);
                                        const pct = total ? Math.round(Number(ctx.raw) / total * 100) : 0;
                                        return ` ${ctx.label}: ${pesos(ctx.raw)} (${pct}%)`;
                                    }
                                }
                            }
                        }"""
if old in s:
    s = s.replace(old, new, 1)
else:
    print("  !! dashboard_charts.js: no encontré el bloque de la dona")
tooltip = "tooltip: { callbacks: { label: ctx => ` ${ctx.dataset.label || ctx.label}: ${pesos(ctx.raw)}` } }"
s = s.replace("plugins: { legend: { display: false } }", "plugins: { legend: { display: false }, " + tooltip + " }")
s = s.replace("""                    plugins: {
                        legend: { display: false }
                    }""", """                    plugins: {
                        legend: { display: false },
                        """ + tooltip + """
                    }""")
open('finanzas/static/js/dashboard_charts.js', 'w', encoding='utf-8', newline='\n').write(s); print('OK finanzas/static/js/dashboard_charts.js')

# 8. importar_csv.py: guardar fila por fila (reglas del libro)
aplicar('importar_csv.py', [
    ("""registro_transacciones.objects.bulk_create(objs, batch_size=500)
print(f"Insertados {len(objs)} movimientos.\"""",
     """# Guardamos uno por uno para que apliquen las reglas del libro (p. ej. una transferencia
# a un préstamo se registra como pago de mensualidad y marca su cuota).
for obj in objs:
    obj.save()
print(f"Insertados {len(objs)} movimientos.\""""),
])

# Comprobación de sintaxis de los .py
import py_compile
for p in ('finanzas/tasks.py', 'finanzas/services/ai_service.py', 'finanzas/forms.py', 'finanzas/views/cuentas.py', 'importar_csv.py'):
    py_compile.compile(p, doraise=True)
print("sintaxis python OK")
