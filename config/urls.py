"""
URLs principales del proyecto CESFAM Farmacia Web.
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from core import error_views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('errores/<str:codigo>/', error_views.preview_error, name='preview_error'),
    path('404-test/', error_views.error_404, name='error_404_test'),
    path('404-test', error_views.error_404, name='error_404_test_no_slash'),
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

# Handlers oficiales de errores HTTP (400, 403, 404 y 500)
handler400 = 'core.error_views.error_400'
handler403 = 'core.error_views.error_403'
handler404 = 'core.error_views.error_404'
handler500 = 'core.error_views.error_500'

# Personalización del Admin
admin.site.site_header = 'CESFAM Farmacia - Administración'
admin.site.site_title = 'CESFAM Farmacia'
admin.site.index_title = 'Panel de Administración'
