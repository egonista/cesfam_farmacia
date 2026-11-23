"""
URLs principales del proyecto CESFAM Farmacia Web.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('farmacia/', include('farmacia.urls')),
    path('dispensacion/', include('dispensacion.urls')),
    path('ges/', include('ges.urls')),
    path('controlados/', include('controlados.urls')),
    path('carros/', include('carros_clinicos.urls')),
    path('reportes/', include('reportes.urls')),
    path('api/', include('api.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

# Personalización del Admin
admin.site.site_header = 'CESFAM Farmacia - Administración'
admin.site.site_title = 'CESFAM Farmacia'
admin.site.index_title = 'Panel de Administración'
