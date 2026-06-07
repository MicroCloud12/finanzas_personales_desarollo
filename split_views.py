import os
import re

SOURCE_FILE = r'c:\Users\Mauricio\Documents\Github\finanzas_personales_desarollo\finanzas\views.py'
TARGET_DIR = r'c:\Users\Mauricio\Documents\Github\finanzas_personales_desarollo\finanzas\views'

if not os.path.exists(TARGET_DIR):
    os.makedirs(TARGET_DIR)

# Mapping of views to modules
MODULE_MAP = {
    'auth.py': ['home', 'iniciosesion', 'registro', 'enviar_pregunta', 'mi_perfil', 'politica_privacidad', 'terminos_servicio'],
    'cuentas.py': ['gestionar_cuentas', 'editar_cuenta', 'eliminar_cuenta'],
    'transacciones.py': [
        'crear_transacciones', 'lista_transacciones', 'editar_transaccion', 'eliminar_transaccion',
        'aprobar_todos_tickets', 'rechazar_todos_tickets', 'aprobar_ticket', 'revisar_tickets', 'rechazar_ticket',
        'iniciar_procesamiento_drive', 'get_initial_task_result', 'get_group_status', 'vista_procesamiento_automatico'
    ],
    'dashboard.py': [
        'vista_dashboard', 'datos_gastos_categoria', 'datos_presupuesto', 'datos_flujo_dinero',
        'datos_inversiones', 'api_ingresos_tarjeta', 'datos_ganancias_mensuales'
    ],
    'inversiones.py': [
        'vista_portafolio', 'lista_inversiones', 'crear_inversion', 'editar_inversion', 'eliminar_inversion',
        'vista_procesamiento_inversiones', 'iniciar_procesamiento_inversiones', 'revisar_inversiones',
        'aprobar_inversion', 'rechazar_inversion', 'aprobar_todas_inversiones', 'rechazar_todas_inversiones'
    ],
    'deudas.py': [
        'lista_deudas', 'crear_deuda', 'detalle_deuda', 'editar_deuda', 'eliminar_deuda',
        'vista_procesamiento_deudas', 'iniciar_procesamiento_deudas', 'revisar_amortizaciones',
        'aprobar_amortizacion', 'rechazar_amortizacion'
    ],
    'suscripciones.py': [
        'gestionar_suscripcion', 'suscripcion_exitosa', 'suscripcion_fallida', 'mercadopago_webhook', 'risc_webhook'
    ],
    'facturacion.py': [
        'facturacion', 'iniciar_procesamiento_facturacion', 'revisar_facturas_pendientes',
        'vista_procesamiento_facturacion', 'revisar_factura_individual', 'revisar_factura_detalle',
        'marcar_como_facturado', 'eliminar_factura_pendiente', 'eliminar_todas_facturas_pendientes',
        'marcar_ticket_facturado', 'actualizar_json_factura', 'editar_factura_registro', 'eliminar_factura_registro',
        'guardar_configuracion_tienda', 'confirmar_datos_factura', 'agregar_campo_tienda', 'eliminar_campo_tienda'
    ],
    'presupuesto.py': [
        'presupuesto_view', 'revisar_historicos', 'crear_presupuesto', 'editar_presupuesto',
        'buscar_recibos_presupuesto', 'procesar_recibos_anteriores_presupuesto', 'predecir_recibo_presupuesto'
    ]
}

# Reverse map
FUNC_TO_MODULE = {}
for mod, funcs in MODULE_MAP.items():
    for f in funcs:
        FUNC_TO_MODULE[f] = mod

with open(SOURCE_FILE, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Extract imports
imports_lines = []
code_lines = lines
for i, line in enumerate(lines):
    if line.startswith('@') or line.startswith('def ') or line.startswith("'''") or line.startswith('"""') or line.startswith('logger ='):
        code_lines = lines[i:]
        break
    imports_lines.append(line)

modules_content = {mod: imports_lines.copy() + ['logger = logging.getLogger(__name__)\n\n'] for mod in MODULE_MAP.keys()}

current_module = None
current_buffer = []
is_in_func = False

def push_buffer():
    global current_buffer, current_module
    if current_module and current_buffer:
        modules_content[current_module].extend(current_buffer)
    current_buffer = []
    current_module = None

i = 0
while i < len(code_lines):
    line = code_lines[i]
    
    # Check if starting a new function
    match = re.match(r'^(?:@\w+.*|def (\w+)\(.*)', line)
    
    # If it's a decorator, let's look ahead to find the def
    if line.startswith('@'):
        j = i
        found_def = None
        while j < len(code_lines) and (code_lines[j].startswith('@') or code_lines[j].strip() == ''):
            j += 1
        if j < len(code_lines) and code_lines[j].startswith('def '):
            m = re.match(r'^def (\w+)\(', code_lines[j])
            if m:
                found_def = m.group(1)
        
        if found_def and found_def in FUNC_TO_MODULE:
            push_buffer()
            current_module = FUNC_TO_MODULE[found_def]
            is_in_func = True

    elif line.startswith('def '):
        m = re.match(r'^def (\w+)\(', line)
        if m:
            func_name = m.group(1)
            if func_name in FUNC_TO_MODULE:
                push_buffer()
                current_module = FUNC_TO_MODULE[func_name]
                is_in_func = True
            else:
                # print(f"Warning: function {func_name} not mapped")
                if current_module is None:
                    current_module = 'auth.py' # fallback
    
    if is_in_func and re.match(r"^(?:'''|\"\"\")", line):
        # Docstrings at root level sometimes happen between functions
        pass
        
    current_buffer.append(line)
    i += 1

push_buffer()

for mod, content in modules_content.items():
    with open(os.path.join(TARGET_DIR, mod), 'w', encoding='utf-8') as f:
        f.writelines(content)

with open(os.path.join(TARGET_DIR, '__init__.py'), 'w', encoding='utf-8') as f:
    f.write("# Init file for views module\n")
    for mod in MODULE_MAP.keys():
        f.write(f"from .{mod[:-3]} import *\n")

print("Finished splitting views.")
