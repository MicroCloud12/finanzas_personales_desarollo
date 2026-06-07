import os

VIEWS_DIR = r'c:\Users\Mauricio\Documents\Github\finanzas_personales_desarollo\finanzas\views'

for filename in os.listdir(VIEWS_DIR):
    if filename.endswith('.py'):
        filepath = os.path.join(VIEWS_DIR, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Replace local imports
        content = content.replace('from .utils import', 'from ..utils import')
        content = content.replace('from .tasks import', 'from ..tasks import')
        content = content.replace('from .forms import', 'from ..forms import')
        content = content.replace('from .services import', 'from ..services import')
        content = content.replace('from .models import', 'from ..models import')
        
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)

print("Finished fixing relative imports in views folder.")
