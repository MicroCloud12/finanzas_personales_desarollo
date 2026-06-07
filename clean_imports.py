import re

file_path = r"c:\Users\Mauricio\Documents\Github\finanzas_personales_desarollo\finanzas\views.py"

with open(file_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    stripped = line.strip()
    if stripped in [
        "import json",
        "from django.http import JsonResponse",
        "from .models import Cuenta",
        "from .models import Presupuesto",
        "from .models import Factura",
        "from .models import TiendaFacturacion",
        "from .models import Presupuesto, HistorialReciboServicio",
        "from .models import HistorialReciboServicio",
    ]:
        continue # Skip these lines
    new_lines.append(line)

with open(file_path, "w", encoding="utf-8") as f:
    f.writelines(new_lines)

print("Finished cleaning up local imports.")
