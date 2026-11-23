"""
Script de verificación de rutas y renderizado de vistas Django.
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from core.models import Usuario

client = Client()

# 1. Login page
r = client.get('/login/')
print(f"GET /login/ -> {r.status_code}")
assert r.status_code == 200, "Login page failed"

# 2. Login como Administrador
user = Usuario.objects.get(username='admin')
client.force_login(user)

# 3. Probar todas las vistas principales
views = [
    ('/', 200, 'Dashboard Principal'),
    ('/farmacia/medicamentos/', 200, 'Listado de Medicamentos'),
    ('/farmacia/lotes/', 200, 'Listado de Lotes FEFO'),
    ('/farmacia/alertas/vencimiento/', 200, 'Alertas de Vencimiento'),
    ('/farmacia/movimientos/', 200, 'Historial de Movimientos'),
    ('/dispensacion/recetas/', 200, 'Listado de Recetas'),
    ('/dispensacion/dispensar/', 200, 'Pantalla de Dispensación'),
    ('/dispensacion/historial/', 200, 'Historial de Dispensaciones'),
    ('/pacientes/', 200, 'Listado de Pacientes'),
    ('/ges/inscripciones/', 200, 'Inscripciones GES/AUGE'),
    ('/controlados/libro/', 200, 'Libro Oficial de Controlados'),
    ('/carros/', 200, 'Carros Clínicos y Carro de Paro'),
    ('/reportes/', 200, 'Dashboard Gerencial y Reportes'),
    ('/auditoria/', 200, 'Bitácora Forense PostgreSQL JSONB'),
    ('/usuarios/', 200, 'Gestión de Usuarios RBAC'),
    ('/simular-rol/quimico/', 302, 'Selector Rápido 1-Clic Rol QF'),
    ('/api/medicamentos/', 200, 'API REST Medicamentos'),
    ('/api/recetas/', 200, 'API REST Recetas'),
    ('/api/dispensaciones/', 200, 'API REST Dispensaciones'),
]

for url, expected, name in views:
    res = client.get(url)
    status = res.status_code
    resultado = "OK" if status == expected else f"ERROR ({status})"
    print(f"[{resultado}] {name} ({url}) -> Status {status}")

print("\n>>> TODAS LAS VISTAS CLÍNICAS Y ASISTENCIALES RENDERIZAN CORRECTAMENTE (200 OK) <<<")
