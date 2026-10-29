"""
Catálogo de categorías de gasto/ingreso y sugerencias para registrar
movimientos con el menor esfuerzo posible.
"""
import re


CATEGORIAS_BASE = [
    'Comida', 'Transporte', 'Carro', 'Combustible', 'Supermercado', 'Entretenimiento',
    'Servicios', 'Nomina', 'Mascotas', 'Ahorro', 'Suscripciones', 'Salud', 'Educación',
    'Impuestos', 'Inversion', 'Tiendas de conveniencia', 'Ropa', 'Alquiler', 'Pareja',
    'Viajes', 'Regalos', 'Gastos varios', 'Tecnología', 'Deudas', 'Otro',
]
CATEGORIA_POR_DEFECTO = 'Otro'


NOMBRE_CUENTA_AHORRO = 'Cuenta Ahorro'
PALABRAS_AHORRO = ('ahorro', 'ahorros', 'cajita', 'cajitas', 'apartado', 'meta')
SENTINELA_NUEVA_AHORRO = '__NUEVA_AHORRO__'
# Palabras de nombres de cuenta que no sirven para reconocer la cuenta en una descripción
PALABRAS_GENERICAS = {'debito', 'débito', 'credito', 'crédito', 'tarjeta', 'cuenta', 'banco', 'de', 'la', 'el',
                      'mi', 'tdc', 'tdd', 'card', 'cash', 'efectivo', 'principal'}


def es_ahorro(texto):
    texto = (texto or '').lower()
    return any(p in texto for p in PALABRAS_AHORRO)


def cuenta_ahorro_para(user, crear=True):
    """La cuenta de AHORRO del usuario; si no tiene, se crea 'Cuenta Ahorro' (opcional)."""
    from .models import Cuenta
    cuenta = Cuenta.objects.filter(propietario=user, tipo='AHORRO').order_by('-es_principal', 'id').first()
    if cuenta is None and crear:
        cuenta, _ = Cuenta.objects.get_or_create(
            propietario=user, nombre=NOMBRE_CUENTA_AHORRO, defaults={'tipo': 'AHORRO'})
        if cuenta.tipo != 'AHORRO':
            cuenta.tipo = 'AHORRO'
            cuenta.save(update_fields=['tipo'])
    return cuenta


def categorias_para(user):
    """Categorías base + las que el usuario ya haya usado en sus movimientos."""
    from .models import registro_transacciones
    usadas = (registro_transacciones.objects.filter(propietario=user)
              .exclude(categoria='').values_list('categoria', flat=True).distinct())
    base_lower = {c.lower() for c in CATEGORIAS_BASE}
    extra = sorted({c for c in usadas if c and c.lower() not in base_lower})
    return CATEGORIAS_BASE + extra


DESCRIPCIONES_GENERICAS = {'', 'SIN DESCRIPCIÓN', 'SIN DESCRIPCION', 'N/A', 'DEPÓSITO', 'DEPOSITO',
                           'CONSULTA DE SALDO', 'SALDO', 'ABONO', 'TRANSFERENCIA', 'SPEI'}


def descripcion_final(datos, tipo, categoria):
    """Descripción con la que se guarda el movimiento. Un ingreso de categoría Nómina
    con descripción genérica se guarda como 'NÓMINA'."""
    descripcion = descripcion_de_ticket(datos)
    if tipo == 'INGRESO' and (categoria or '').strip().lower() in ('nomina', 'nómina') \
            and descripcion.strip().upper() in DESCRIPCIONES_GENERICAS:
        return 'NÓMINA'
    return descripcion


def descripcion_de_ticket(datos):
    """Misma descripción que se guardará al aprobar el ticket (para buscar en el historial)."""
    tipo_documento = datos.get("tipo_documento")
    tipo_movimiento = datos.get("tipo_movimiento")
    descripcion = datos.get("descripcion_corta") or "Sin descripción"
    if tipo_documento == 'TRANSFERENCIA' or tipo_movimiento == 'TRANSFERENCIA':
        descripcion = re.sub(r'(?i)^transferencias?\s*(de|por)?\s*', '', descripcion).strip()
    elif tipo_documento == 'TICKET_COMPRA' or tipo_movimiento == 'GASTO':
        descripcion = datos.get("establecimiento") or descripcion
    return (descripcion or "Sin descripción").upper()


def _a_decimal(valor):
    from decimal import Decimal, InvalidOperation
    try:
        return Decimal(str(valor).replace(',', '').replace('$', '').strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def monto_de_ticket(datos):
    return _a_decimal(datos.get('total') or datos.get('total_pagado') or 0) or 0


def clasificar_ticket(datos):
    """
    'MOVIMIENTO' -> tiene monto: se puede registrar.
    'SIN_MONTO'  -> la IA no detectó un monto; el usuario lo puede escribir en la fila.
    """
    return 'MOVIMIENTO' if monto_de_ticket(datos) > 0 else 'SIN_MONTO'


def tipo_sugerido_por_ia(datos):
    tipo = (datos.get("tipo_movimiento") or "").upper()
    if tipo in ('GASTO', 'INGRESO', 'TRANSFERENCIA', 'PAGO_MENSUALIDAD', 'PAGO_CAPITAL'):
        return tipo
    if datos.get("tipo_documento") == 'TRANSFERENCIA':
        return 'TRANSFERENCIA'
    if datos.get("tipo_documento") == 'TICKET_COMPRA':
        return 'GASTO'
    if datos.get("tipo_documento") == 'CAPTURA_BANCO':
        return 'INGRESO'
    return ''


class Sugeridor:
    """
    Decide los valores por defecto de un ticket pendiente con esta prioridad:
      1. Lo que la IA extrajo del ticket (si la cuenta existe en el catálogo).
      2. El último movimiento aprobado con la misma descripción (historial).
      3. La cuenta principal del usuario.
    """

    def __init__(self, user):
        from .models import Cuenta, registro_transacciones
        self.user = user
        self.cuentas = list(Cuenta.objects.filter(propietario=user).order_by('-es_principal', 'tipo', 'nombre'))
        self.por_nombre = {c.nombre.strip().upper(): c for c in self.cuentas}
        self.por_terminacion = {c.terminacion.strip()[-4:]: c for c in self.cuentas if c.terminacion and c.terminacion.strip()}
        self.principal = next((c for c in self.cuentas if c.es_principal), None) or (self.cuentas[0] if self.cuentas else None)
        self._tx = registro_transacciones.objects.filter(propietario=user).select_related('origen', 'destino')

    def cuenta(self, nombre):
        nombre = (nombre or '').strip()
        if not nombre or nombre.upper() in {'N/A', 'OTRA CUENTA', 'SIN CUENTA'}:
            return None
        c = self.por_nombre.get(nombre.upper())
        if c is None:
            digitos = re.findall(r'\d{4}', nombre)
            if digitos:
                c = self.por_terminacion.get(digitos[-1])
        return c

    def cuenta_mencionada(self, texto, excluir=None, preferir_pasivo=False):
        """Busca el nombre de alguna cuenta dentro de un texto ('Mauricio nu' -> 'NU (Debito)')."""
        texto_n = (texto or '').lower()
        palabras_texto = set(re.findall(r'[a-záéíóúñ]+', texto_n))
        if not texto_n.strip():
            return None
        candidatas = []
        for c in self.cuentas:
            if excluir is not None and c.id == excluir.id:
                continue
            palabras = {w for w in re.findall(r'[a-záéíóúñ0-9]+', c.nombre.lower()) if w not in PALABRAS_GENERICAS and len(w) >= 2}
            # Nombres de 3+ letras se buscan como subcadena ("digitt" dentro de "digitt001mensualidad");
            # los muy cortos ("nu") solo como palabra completa para no confundirlos.
            if any((len(w) >= 3 and w in texto_n) or (len(w) < 3 and w in palabras_texto) for w in palabras):
                candidatas.append(c)
        if not candidatas:
            return None
        candidatas.sort(key=lambda c: (c.es_pasivo != preferir_pasivo, c.nombre))
        return candidatas[0]

    def historial(self, descripcion):
        if not descripcion:
            return None
        return self._tx.filter(descripcion__iexact=descripcion).order_by('-fecha', '-id').first()

    def sugerir(self, datos):
        descripcion = descripcion_de_ticket(datos)
        previo = self.historial(descripcion)
        aviso = ''

        tipo = tipo_sugerido_por_ia(datos) or (previo.tipo if previo else 'GASTO')
        categoria = (datos.get('categoria_sugerida') or '').strip() or (previo.categoria if previo else '')

        origen = self.cuenta(datos.get('cuenta_origen_sugerida'))
        destino = self.cuenta(datos.get('cuenta_destino_sugerida'))
        if previo is not None:
            if origen is None and previo.origen_id:
                origen = previo.origen
            if destino is None and previo.destino_id:
                destino = previo.destino
        # Para un ingreso la "cuenta" protagonista es a la que entra el dinero.
        if tipo == 'INGRESO' and origen is None:
            origen, destino = destino, None
        if origen is None:
            origen = self.principal

        # ¿Es un ahorro? (categoría o descripción). Nunca es gasto: va a la cuenta de ahorro.
        parece_ahorro = es_ahorro(categoria) or es_ahorro(descripcion) or es_ahorro(datos.get('descripcion_corta'))
        if tipo in ('GASTO', 'TRANSFERENCIA') and parece_ahorro:
            tipo = 'TRANSFERENCIA'
            categoria = 'Ahorro'
            if destino is None or destino.tipo != 'AHORRO':
                destino = cuenta_ahorro_para(self.user, crear=False)
            if destino is None:
                aviso = 'Se creará tu cuenta "Cuenta Ahorro" al aprobar.'

        # "Gasto" de categoría Deudas que menciona una tarjeta o préstamo tuyo: es un pago de deuda.
        if tipo == 'GASTO' and destino is None and (categoria or '').lower() == 'deudas':
            pasivo = self.cuenta_mencionada(descripcion, excluir=origen, preferir_pasivo=True)
            if pasivo is not None and pasivo.es_pasivo:
                tipo, destino = 'TRANSFERENCIA', pasivo

        # Transferencia sin destino: ¿la descripción menciona una cuenta tuya? ("Mauricio nu")
        if tipo == 'TRANSFERENCIA' and destino is None and not parece_ahorro:
            destino = self.cuenta_mencionada(descripcion, excluir=origen, preferir_pasivo=(categoria or '').lower() == 'deudas')
            if destino is not None and not categoria:
                categoria = 'Deudas' if destino.es_pasivo else 'Transferencia'

        # Una transferencia que no llega a ninguna cuenta tuya es un pago a un tercero: gasto.
        if tipo == 'TRANSFERENCIA' and destino is None and not parece_ahorro:
            tipo = 'GASTO'

        destino_valor = destino.nombre if destino else ('' if not (parece_ahorro and tipo == 'TRANSFERENCIA') else SENTINELA_NUEVA_AHORRO)
        return {
            'tipo': tipo,
            'categoria': categoria,
            'origen': origen.nombre if origen else '',
            'destino': destino_valor,
            'aviso': aviso,
            'fuente': 'historial' if previo is not None else ('ia' if datos.get('cuenta_origen_sugerida') else 'principal'),
        }
