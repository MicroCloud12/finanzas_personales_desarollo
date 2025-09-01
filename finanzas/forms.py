from django import forms
from django.contrib.auth.models import User
from django.contrib.auth.forms import UserCreationForm
from .models import registro_transacciones, inversiones, Deuda, PagoAmortizacion

class TransaccionesForm(forms.ModelForm):
    class Meta:
        model = registro_transacciones
        exclude = ('propietario',)
        widgets = {
            'fecha': forms.DateInput(attrs={'type': 'date','class': 'appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'descripcion': forms.Textarea(attrs={'rows': 3, 'class': 'appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'categoria': forms.TextInput(attrs={'class': 'appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'monto': forms.NumberInput(attrs={'class': 'appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'tipo': forms.Select(attrs={'class': 'block w-full px-3 py-2 border border-gray-300 bg-white rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'cuenta_origen': forms.TextInput(attrs={'class': 'appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'cuenta_destino': forms.TextInput(attrs={'class': 'appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'deuda_asociada': forms.Select(attrs={'class': 'block w-full px-3 py-2 border border-gray-300 bg-white rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
            'tipo_pago':forms.Select(attrs={'class': 'block w-full px-3 py-2 border border-gray-300 bg-white rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm'}),
        }

    def __init__(self, *args, **kwargs):
        # --- ¡AQUÍ ESTÁ LA CORRECCIÓN CLAVE! ---
        # 1. Atrapamos el 'user' que nos pasa la vista.
        user = kwargs.pop('user', None)

        # 2. Llamamos al constructor original, PERO ya sin el argumento 'user'.
        super(TransaccionesForm, self).__init__(*args, **kwargs)

        # 3. Ahora que el formulario está inicializado, podemos modificar sus campos.
        if user:
            self.fields['deuda_asociada'].queryset = Deuda.objects.filter(propietario=user)

        self.fields['deuda_asociada'].required = False
        self.fields['deuda_asociada'].label = "Deuda Asociada (Opcional)"
        self.fields['deuda_asociada'].empty_label = "Ninguna"

        # Aplicamos estilos
        tailwind_select_classes = "block w-full px-3 py-2 border border-gray-300 bg-white rounded-md shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
        tailwind_input_classes = "appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"

        for field_name, field in self.fields.items():
            widget = field.widget
            if isinstance(widget, forms.Select):
                widget.attrs.update({'class': tailwind_select_classes})
            elif isinstance(widget, forms.DateInput):
                widget.attrs.update({'class': tailwind_input_classes, 'type': 'date'})
            else:
                widget.attrs.update({'class': tailwind_input_classes})

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
    Formulario para crear y actualizar deudas, con estilos de Tailwind.
    """
    class Meta:
        model = Deuda
        # Excluimos los campos que se calculan automáticamente o los asigna el sistema.
        exclude = ('propietario', 'saldo_pendiente')
        
        # Textos de ayuda para guiar al usuario
        help_texts = {
            'nombre': "Dale un apodo fácil de recordar (ej. 'Tarjeta Banamex', 'Crédito Coche').",
            'tasa_interes': "Ingresa la Tasa de Interés Anual (Ej: 16.5 para 16.5%).",
            'plazo_meses': "Para tarjetas de crédito, puedes dejarlo en 1."
        }

    def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            
            # Clases de Tailwind para aplicar a los campos
            input_classes = "appearance-none block w-full px-3 py-2 border border-gray-300 rounded-md shadow-sm placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"
            select_classes = "block w-full px-3 py-2 border border-gray-300 bg-white rounded-md shadow-sm focus:outline-none focus:ring-indigo-500 focus:border-indigo-500 sm:text-sm"

            # Aplicamos los estilos a cada campo
            for field_name, field in self.fields.items():
                if isinstance(field.widget, forms.Select):
                    # --- ¡AQUÍ ESTABA EL ERROR CORREGIDO! ---
                    field.widget.attrs.update({'class': select_classes})
                else:
                    field.widget.attrs.update({'class': input_classes})
                    
            # Hacemos que el campo de fecha use el widget de fecha de HTML5
            self.fields['fecha_adquisicion'].widget = forms.DateInput(
                attrs={'type': 'date', 'class': input_classes}
        )
            
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