"""
Suite de humo (Smoke Test) + Matriz RBAC estricta de los 4 roles,
endpoints JSON en tiempo real/AJAX y exportaciones Excel (.xlsx) y PDF.
"""
import os
import json
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import Client
from core.models import Usuario
from carros_clinicos.models import CarroClinico
from farmacia.models import OrdenAbastecimiento

client = Client()

# 1. Login page
r = client.get('/login/')
assert r.status_code == 200, f"Login fallo: {r.status_code}"
print(f"[OK] GET /login/ -> {r.status_code}")

# Usuarios base
admin = Usuario.objects.get(username='admin')
qf = Usuario.objects.get(username='qf_suazo')
tecnico = Usuario.objects.get(username='tecnico_alvarez')
clinico = Usuario.objects.get(username='enfermera_gonzalez')
primer_carro = CarroClinico.objects.filter(activo=True).first()
primera_orden = OrdenAbastecimiento.objects.first()

# ============================================================
# ROL 1: ADMINISTRADOR (DOCENTE)
# ============================================================
client.force_login(admin)
admin_200 = [
    ('/', 'Dashboard Admin'),
    ('/usuarios/', 'Usuarios y Roles'),
    ('/admin-panel/escenarios/', 'Escenarios de Simulación'),
    ('/admin-panel/escenarios/nuevo/', 'Nuevo Escenario'),
    ('/admin-panel/banco-pacientes/', 'Banco de Pacientes'),
    ('/pacientes/', 'Pacientes'),
    ('/pacientes/crear/', 'Nuevo Paciente'),
    ('/dispensacion/recetas/', 'Recetas Médicas'),
    ('/dispensacion/recetas/crear/', 'Nueva Receta'),
    ('/farmacia/medicamentos/', 'Arsenal Farmacológico'),
    ('/farmacia/lotes/', 'Lotes FEFO'),
    ('/farmacia/abastecimiento/', 'Pedidos CENABAST'),
    ('/carros/', 'Carros Clínicos'),
    ('/reportes/', 'Reportes Gerenciales'),
    ('/auditoria/', 'Auditoría'),
    ('/api/medicamentos/', 'API Medicamentos'),
    ('/api/recetas/', 'API Recetas'),
    ('/api/dispensaciones/', 'API Dispensaciones'),
]
if primer_carro:
    admin_200.append((f'/carros/{primer_carro.pk}/', 'Detalle Carro Clínico'))

for url, nombre in admin_200:
    res = client.get(url)
    assert res.status_code == 200, f"Admin {nombre} ({url}) -> {res.status_code}"

# JSON tiempo real + AJAX validación (sin ensuciar BD) + Excel + PDF
res_estado = client.get('/api/simulacion/estado/')
assert res_estado.status_code == 200 and 'version' in res_estado.json(), "Fallo /api/simulacion/estado/"

res_ajax_val = client.post(
    '/admin-panel/escenarios/api/paciente/',
    json.dumps({'rut': '12.345.678-0'}),
    content_type='application/json',
)
assert res_ajax_val.status_code == 400 and res_ajax_val.json().get('ok') is False, "AJAX paciente debe validar 400"

res_xlsx = client.get('/reportes/exportar/excel/')
assert res_xlsx.status_code == 200 and len(res_xlsx.content) > 500, "Excel (.xlsx) vacío o fallido"
res_pdf = client.get('/reportes/exportar/pdf/')
assert res_pdf.status_code == 200 and res_pdf.content.startswith(b'%PDF'), "PDF inválido o fallido"

# Bloqueos 403 Admin en operación clínica directa
for url in ('/controlados/libro/', '/dispensacion/dispensar/', '/farmacia/movimientos/traspaso/'):
    assert client.get(url).status_code == 403, f"Admin debe recibir 403 en {url}"

# /simular-rol/ permitido para Admin real (302)
assert client.get('/simular-rol/quimico/').status_code == 302, "Admin debe poder usar /simular-rol/quimico/"
assert client.get('/simular-rol/admin/').status_code == 302, "Admin debe poder volver a /simular-rol/admin/"
print("[OK] Rol 1 (Administrador): Dashboard, Usuarios, Escenarios CRUD, Banco Pacientes, Reportes (Excel/PDF), APIs y /simular-rol/ -> OK | Bloqueos 403 -> OK")

# ============================================================
# ROL 2: QUÍMICO FARMACÉUTICO
# ============================================================
client.logout()
client.force_login(qf)
qf_200 = [
    ('/', 'Dashboard Q.F.'),
    ('/controlados/libro/', 'Libro de Controlados ISP'),
    ('/dispensacion/dispensar/', 'Ventanilla de Dispensación'),
    ('/dispensacion/recetas/', 'Recetas Médicas'),
    ('/dispensacion/historial/', 'Historial Dispensaciones'),
    ('/farmacia/medicamentos/', 'Arsenal'),
    ('/farmacia/lotes/', 'Lotes FEFO'),
    ('/farmacia/alertas/vencimiento/', 'Semáforo FEFO'),
    ('/farmacia/movimientos/', 'Movimientos Stock'),
    ('/farmacia/abastecimiento/', 'Pedidos CENABAST'),
    ('/pacientes/', 'Pacientes'),
    ('/ges/inscripciones/', 'Cuotas GES'),
    ('/carros/', 'Carros Clínicos'),
    ('/reportes/', 'Reportes'),
    ('/auditoria/', 'Auditoría'),
    ('/api/simulacion/estado/', 'API Estado Simulación'),
]
for url, nombre in qf_200:
    res = client.get(url)
    assert res.status_code == 200, f"Q.F. {nombre} ({url}) -> {res.status_code}"

assert client.get('/reportes/exportar/excel/').status_code == 200, "Q.F. debe descargar Excel"
assert client.get('/reportes/exportar/pdf/').content.startswith(b'%PDF'), "Q.F. debe descargar PDF"

for url in (
    '/usuarios/',
    '/admin-panel/escenarios/',
    '/admin-panel/banco-pacientes/',
    '/simular-rol/tecnico/',
):
    assert client.get(url).status_code == 403, f"Q.F. debe recibir 403 en {url}"
assert client.post('/admin-panel/escenarios/api/paciente/', {}, HTTP_ACCEPT='application/json').status_code == 403
print("[OK] Rol 2 (Químico Farmacéutico): Controlados ISP, Dispensación, Lotes, CENABAST, Reportes (Excel/PDF) -> OK | /usuarios/, /escenarios/, /simular-rol/ -> 403")

# ============================================================
# ROL 3: TÉCNICO EN FARMACIA
# ============================================================
client.logout()
client.force_login(tecnico)
tec_200 = [
    ('/', 'Dashboard Técnico'),
    ('/dispensacion/dispensar/', 'Ventanilla de Dispensación'),
    ('/dispensacion/recetas/', 'Recetas Médicas'),
    ('/dispensacion/historial/', 'Historial Dispensaciones'),
    ('/farmacia/medicamentos/', 'Arsenal'),
    ('/farmacia/lotes/', 'Lotes FEFO'),
    ('/farmacia/movimientos/', 'Movimientos Stock'),
    ('/farmacia/movimientos/traspaso/', 'Traspaso Bodega->Vitrina'),
    ('/farmacia/alertas/vencimiento/', 'Semáforo FEFO'),
    ('/farmacia/abastecimiento/', 'Pedidos CENABAST'),
    ('/pacientes/', 'Pacientes'),
    ('/ges/inscripciones/', 'Cuotas GES'),
    ('/carros/', 'Carros Clínicos'),
    ('/api/simulacion/estado/', 'API Estado Simulación'),
]
for url, nombre in tec_200:
    res = client.get(url)
    assert res.status_code == 200, f"Técnico {nombre} ({url}) -> {res.status_code}"

for url in (
    '/usuarios/',
    '/controlados/libro/',
    '/pacientes/crear/',
    '/auditoria/',
    '/reportes/',
    '/reportes/exportar/excel/',
    '/reportes/exportar/pdf/',
    '/admin-panel/escenarios/',
    '/admin-panel/banco-pacientes/',
    '/simular-rol/admin/',
):
    assert client.get(url).status_code == 403, f"Técnico debe recibir 403 en {url}"

assert client.post('/admin-panel/escenarios/api/paciente/', {}, HTTP_ACCEPT='application/json').status_code == 403
if primera_orden:
    assert client.post(f'/farmacia/abastecimiento/{primera_orden.pk}/', {'accion': 'aprobar'}).status_code == 403
print("[OK] Rol 3 (Técnico en Farmacia): Ventanilla FEFO, Traspasos, Carros -> OK | Usuarios, Controlados, Reportes, Aprobación CENABAST, /simular-rol/ -> 403")

# ============================================================
# ROL 4: PERSONAL CLÍNICO (ENFERMERÍA)
# ============================================================
client.logout()
client.force_login(clinico)
for url, nombre in (
    ('/', 'Dashboard Clínico'),
    ('/farmacia/medicamentos/', 'Consulta Arsenal'),
    ('/carros/', 'Carros Clínicos'),
    ('/api/simulacion/estado/', 'API Estado Simulación'),
):
    res = client.get(url)
    assert res.status_code == 200, f"Clínico {nombre} ({url}) -> {res.status_code}"

for url in (
    '/pacientes/',
    '/dispensacion/recetas/',
    '/dispensacion/dispensar/',
    '/farmacia/lotes/',
    '/controlados/libro/',
    '/usuarios/',
    '/auditoria/',
    '/reportes/',
    '/admin-panel/escenarios/',
    '/simular-rol/admin/',
    '/api/pacientes/',
):
    assert client.get(url).status_code == 403, f"Clínico debe recibir 403 en {url}"
print("[OK] Rol 4 (Personal Clínico): Dashboard, Consulta Arsenal, Carros -> OK | Pacientes, Recetas, Dispensación, Lotes, Usuarios, /simular-rol/ -> 403")

print("\n>>> SMOKE TEST + MATRIZ RBAC (4 ROLES) + APIs + EXCEL/PDF: 100% APROBADO <<<")
