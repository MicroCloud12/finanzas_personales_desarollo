from PIL import Image
import os

img_dir = r"C:\Users\Mauricio\Documents\Github\finanzas_personales_desarollo\static\img"
for filename in os.listdir(img_dir):
    if filename.endswith(".jpg") or filename.endswith(".png"):
        img_path = os.path.join(img_dir, filename)
        img = Image.open(img_path)
        webp_path = os.path.join(img_dir, filename.rsplit('.', 1)[0] + '.webp')
        img.save(webp_path, 'webp', optimize=True, quality=80)
        print(f"Converted {filename} to WebP.")
