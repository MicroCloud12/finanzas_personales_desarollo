from django.contrib import admin
from django.urls import path, include
from django.contrib.sitemaps.views import sitemap
from django.views.generic import TemplateView
from finanzas.sitemaps import StaticViewSitemap

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('finanzas.urls')),
    path('accounts/', include('allauth.urls')),
    path('robots.txt', TemplateView.as_view(template_name='robots.txt', content_type='text/plain'), name='robots'),
    path('sitemap.xml', sitemap, {'sitemaps': {'static': StaticViewSitemap}}, name='django.contrib.sitemaps.views.sitemap'),
]
