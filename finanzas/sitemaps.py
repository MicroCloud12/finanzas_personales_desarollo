from django.contrib.sitemaps import Sitemap
from django.urls import reverse

class StaticViewSitemap(Sitemap):
    priority = 0.8
    changefreq = 'monthly'

    def items(self):
        # Lista de las vistas estáticas que quieres incluir
        return ['home', 'login', 'registro_usuarios', 'lista_transacciones', 'lista_inversiones']

    def location(self, item):
        return reverse(item)