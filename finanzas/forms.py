from django import forms
from django.core.exceptions import ValidationError
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import registro_transacciones, inversiones, Deuda, PagoAmortizacion
from .models import Cuenta

INPUT_CLASSES = "appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
SELECT_CLASSES = "block w-full px-3 py-2 border border-gray-300 bg-white rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
CHECKBOX_CLASSES = "h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded"


def _aplicar_estilos(form):
    for field in form.fields.values():
        if isinstance(field.widget, forms.Select):
            field.widget.attrs.update({'class': SELECT_CLASSES})
        elif isinstance(field.widget, forms.CheckboxInput):
            field.widget.attrs.update({'class': CHECKBOX_CLASSES})
        else:
            field.widget.attrs.update({'class': INPUT_CLASSES})


class CuentaForm(forms.ModelForm):
    """
    Alta/edición de cuentas del libro mayor. El usuario captura el SALDO ACTUAL
    (lo que dice su banco hoy) y el formulario lo traduce a `saldo_inicial`
    para que el saldo derivado de los movimientos coincida (conciliación).
    """
    saldo_actual = forms.DecimalField(
        required=False, max_digits=20, decimal_places=2, initial=0,
        label="Saldo actual",
        help_text="Activos: cuánto dinero hay hoy en la cuenta. Tarjetas/préstamos: cuánto debes hoy. "
                  "Se usa para cuadrar el saldo con tus movimientos registrados.")

    class Meta:
        model = Cuenta
        fields = ['nombre', 'terminacion', 'tipo', 'es_principal']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _aplicar_estilos(self)
        self.fields['nombre'].widget.attrs.update({'placeholder': 'Ej. Tarjeta Nu, Efectivo, BBVA'})
        self.fields['terminacion'].widget.attrs.update({'placeholder': 'Ej. 1234 (Solo los últimos 4 números)'})
        if self.instance and self.instance.pk:
            self.fields['saldo_actual'].initial = self.instance.saldo()

    def save(self, commit=True):
        cuenta = super().save(commit=False)
        saldo_actual = self.cleaned_data.get('saldo_actual')
        es_nueva = cuenta.pk is None
        if es_nueva and saldo_actual is not None:
            # Cuenta nueva: no hay movimientos, el saldo actual ES el saldo inicial.
            cuenta.saldo_inicial = saldo_actual
        if commit:
            cuenta.save()
            if not es_nueva and saldo_actual is not None:
                # Cuenta existente: conciliamos contra el saldo real que capturó el usuario.
                cuenta.ajustar_saldo_inicial_para(saldo_actual)
        return cuenta

class TransaccionesForm(forms.ModelForm):
    """
    Captura de movimientos del libro diario.
      INGRESO        -> solo `destino` (a qué cuenta entra)
      GASTO          -> solo `origen`  (con qué cuenta/tarjeta se pagó)
      TRANSFERENCIA  -> origen y destino (pagar tarjeta, ahorrar, mover dinero)
      PAGO_*         -> origen (cuenta) y destino (préstamo)
    """
    class Meta:
        model = registro_transacciones
        fields = ['fecha', 'descripcion', 'categoria', 'monto', 'tipo', 'origen', 'destino', 'monto_interes']
        labels = {
            'origen': 'Cuenta de la que sale',
            'destino': 'Cuenta a la que entra',
            'monto_interes': 'De ese monto, ¿cuánto es interés (+IVA)?',
        }
        widgets = {
            'fecha': forms.DateInput(attrs={'type': 'date'}),
            'descripcion': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.user = user
        cuentas = Cuenta.objects.filter(propietario=user) if user else Cuenta.objects.none()
        self.fields['origen'].queryset = cuentas
        self.fields['destino'].queryset = cuentas
        self.fields['origen'].required = False
        self.fields['destino'].required = False
        self.fields['monto_interes'].required = False
        self.fields['origen'].empty_label = '---------'
        self.fields['destino'].empty_label = '---------'
        _aplicar_estilos(self)
        self.fields['fecha'].widget.attrs.update({'type': 'date'})

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('monto_interes') is None:
            cleaned['monto_interes'] = 0
        # Las reglas de origen/destino por tipo viven en el modelo (clean()).
        # Las ejecutamos aquí para mostrar los errores en el formulario.
        instancia = registro_transacciones(
            propietario=self.user, tipo=cleaned.get('tipo'), monto=cleaned.get('monto'),
            origen=cleaned.get('origen'), destino=cleaned.get('destino'),
            monto_interes=cleaned.get('monto_interes') or 0,
        )
        try:
            instancia.clean()
        except ValidationError as e:
            for campo, mensajes in e.message_dict.items():
                for m in mensajes:
                    self.add_error(campo if campo in self.fields else None, m)
        else:
            cleaned['origen'] = instancia.origen
            cleaned['destino'] = instancia.destino
        return cleaned

class FormularioRegistroPersonalizado(UserCreationForm):
    # El campo de email y la validación que ya teníamos están perfectos.
    email = forms.EmailField(
        required=True,
        help_text='Obligatorio. Introduce una dirección de correo válida.'
    )

    class Meta(UserCreationForm.Meta):
        fields = UserCreationForm.Meta.fields + ('email',)

    # --- AQUÍ VIENE LA NUEVA LÓGICA ---
    # Sobrescribimos el método de inicialización del formulario
    def __init__(self, *args, **kwargs):
        # Primero, ejecutamos la inicialización original
        super().__init__(*args, **kwargs)

        # Ahora, definimos las clases de Tailwind que queremos aplicar
        tailwind_classes = "appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"

        # Iteramos sobre todos los campos del formulario
        for field_name, field in self.fields.items():
            # Y le añadimos las clases a su widget (el input HTML)
            field.widget.attrs.update({'class': tailwind_classes})

    def clean_email(self):
        # Esta función de validación sigue igual
        email = self.cleaned_data.get('email')
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("Este correo electrónico ya está en uso.")
        return email

class InversionForm(forms.ModelForm):
    """
    Formulario para crear y actualizar inversiones, con estilos diferenciados.
    """
    class Meta:
        model = inversiones
        # Es más claro definir los campos que SÍ queremos mostrar.
        fields = [
            'tipo_inversion',
            'nombre_activo',
            'emisora_ticker',
            'cantidad_titulos',
            'fecha_compra',
            'precio_compra_titulo',
            'tipo_cambio_compra',
        ]
        widgets = {
            'fecha_compra': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # --- LÓGICA DE ESTILOS MEJORADA ---

        # Clases para inputs normales (texto, número, fecha)
        input_classes = "appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
        
        # Clases específicas para la lista desplegable (select)
        select_classes = "block w-full px-3 py-2 border border-gray-300 bg-white rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"

        # Aplicamos los estilos de forma condicional
        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.Select):
                # Si el campo es una lista (como 'tipo_inversion')
                field.widget.attrs.update({'class': select_classes})
            else:
                # Para todos los demás campos
                field.widget.attrs.update({'class': input_classes})
        
        # Añadimos textos de ayuda para guiar al usuario
        self.fields['nombre_activo'].help_text = "Ej: 'NVIDIA Corp', 'Bitcoin', 'Fondo de Inversión Global'."
        self.fields['emisora_ticker'].help_text = "Opcional. Ej: 'AAPL' para Apple, 'BIMBOA.MX' para Bimbo."

class DeudaForm(forms.ModelForm):
    """
    Alta/edición de deudas. El saldo NO se captura: se deriva de los movimientos.
    `saldo_actual` sirve para cuadrar (conciliar) lo que debes hoy.
    """
    saldo_actual = forms.DecimalField(
        required=False, max_digits=12, decimal_places=2,
        label="¿Cuánto debes hoy?",
        help_text="Préstamo: capital pendiente. Tarjeta: saldo usado (lo que aparece en tu estado de cuenta). "
                  "Déjalo vacío para no modificarlo.")

    class Meta:
        model = Deuda
        exclude = ('propietario', 'cuenta', 'saldo_legado', 'requiere_configuracion_adicional')
        help_texts = {
            'nombre': "Dale un apodo fácil de recordar (ej. 'Tarjeta Banamex', 'Crédito Coche').",
            'tasa_interes': "Ingresa la Tasa de Interés Anual (Ej: 16.5 para 16.5%).",
            'plazo_meses': "Para tarjetas de crédito, puedes dejarlo en 1.",
            'monto_total': "Préstamo: monto original. Tarjeta: límite de crédito.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _aplicar_estilos(self)
        self.fields['fecha_adquisicion'].widget = forms.DateInput(attrs={'type': 'date', 'class': INPUT_CLASSES})
        if self.instance and self.instance.pk:
            self.fields['saldo_actual'].initial = self.instance.saldo_pendiente

    def save(self, commit=True):
        deuda = super().save(commit=False)
        saldo_actual = self.cleaned_data.get('saldo_actual')
        if commit:
            es_nueva = deuda.pk is None
            if es_nueva:
                inicial = saldo_actual
                if inicial is None:
                    inicial = deuda.monto_total if deuda.tipo_deuda == 'PRESTAMO' else 0
                deuda.save(saldo_inicial=inicial)
            else:
                deuda.save()
                if saldo_actual is not None:
                    deuda.cuenta.ajustar_saldo_inicial_para(saldo_actual)
        return deuda

class PagoAmortizacionForm(forms.ModelForm):
    class Meta:
        model = PagoAmortizacion
        # Incluimos solo los campos que el usuario debe llenar
        fields = ['fecha_vencimiento', 'capital', 'interes', 'iva']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        input_classes = "appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm sm:text-sm"
        
        for field_name, field in self.fields.items():
            field.widget.attrs.update({'class': input_classes})
            
        self.fields['fecha_vencimiento'].widget = forms.DateInput(
            attrs={'type': 'date', 'class': input_classes}
        )

from .models import Presupuesto

class PresupuestoForm(forms.ModelForm):
    class Meta:
        model = Presupuesto
        fields = ['categoria', 'monto_presupuestado', 'monto_real', 'es_recurrente', 'mes', 'anio']
        help_texts = {
            'categoria': "Ej. Vivienda, Alimentación, Transporte.",
            'monto_presupuestado': "Monto límite que planeas gastar en esta categoría.",
            'monto_real': "Monto realmente gastado o facturado en este periodo.",
            'es_recurrente': "Si está activo, este presupuesto se aplicará todos los meses.",
            'mes': "Solo si NO es recurrente. (1-12)",
            'anio': "Solo si NO es recurrente. Ej. 2026",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        input_classes = "appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
        checkbox_classes = "h-4 w-4 text-indigo-600 focus:ring-indigo-500 border-gray-300 rounded"

        for field_name, field in self.fields.items():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({'class': checkbox_classes})
            else:
                field.widget.attrs.update({'class': input_classes})