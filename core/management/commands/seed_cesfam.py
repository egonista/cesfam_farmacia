"""
Comando de inicialización y población de datos para el Sistema CESFAM Farmacia.
Puebla PostgreSQL y MongoDB con datos clínicos chilenos realistas.
Autores: Egon Muñoz Muttel y Renato Suazo Burgos - INACAP 2026.
"""
from datetime import date, timedelta, datetime, timezone
import pyotp
from django.core.management.base import BaseCommand
from django.contrib.auth.hashers import make_password
from django.db import transaction

from core.models import Usuario, Paciente, MedicoPrescriptor, AuditoriaInmutable, AlertaSistema
from core.utils import formatear_rut, registrar_auditoria
from farmacia.models import (
    CategoriaMedicamento, Medicamento, Ubicacion, Lote, MovimientoStock
)
from dispensacion.models import (
    Receta, DetalleReceta, TerceroAutorizado, Dispensacion, DetalleDispensacion
)
from ges.models import PatologiaGES, CanastaGES, InscripcionGES, CuotaGES
from controlados.models import LibroControlados
from carros_clinicos.models import (
    CarroClinico, PlantillaItemCarro, ConsumoCarroClinico, ReposicionCarro
)
from core.mongo_client import get_mongo_db


class Command(BaseCommand):
    help = 'Puebla PostgreSQL y MongoDB con datos chilenos realistas para CESFAM Farmacia'

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("=== Iniciando Seed CESFAM Farmacia ==="))

        hoy = date.today()

        # ----------------------------------------------------
        # 1. USUARIOS (RBAC - 4 Roles)
        # ----------------------------------------------------
        self.stdout.write("1. Creando usuarios con RBAC...")

        # PIN por defecto hasheado para 2FA
        pin_hash = make_password('123456')

        usuarios_data = [
            {
                'username': 'admin',
                'rut': '14.821.934-6',
                'first_name': 'Egon',
                'last_name': 'Muñoz Muttel',
                'email': 'egon.munoz@cesfam.cl',
                'rol': Usuario.Rol.ADMINISTRADOR,
                'is_staff': True,
                'is_superuser': True,
                'pin_seguridad': pin_hash,
            },
            {
                'username': 'qf_suazo',
                'rut': '18.943.210-0',
                'first_name': 'Renato',
                'last_name': 'Suazo Burgos',
                'email': 'renato.suazo@cesfam.cl',
                'rol': Usuario.Rol.QUIMICO_FARMACEUTICO,
                'is_staff': True,
                'is_superuser': False,
                'pin_seguridad': pin_hash,
            },
            {
                'username': 'tecnico_alvarez',
                'rut': '19.876.543-0',
                'first_name': 'Rodrigo',
                'last_name': 'Álvarez Castro',
                'email': 'rodrigo.alvarez@cesfam.cl',
                'rol': Usuario.Rol.TECNICO_FARMACIA,
                'is_staff': False,
                'is_superuser': False,
            },
            {
                'username': 'enfermera_gonzalez',
                'rut': '16.543.210-K',
                'first_name': 'Camila',
                'last_name': 'González Soto',
                'email': 'camila.gonzalez@cesfam.cl',
                'rol': Usuario.Rol.PERSONAL_CLINICO,
                'is_staff': False,
                'is_superuser': False,
            },
        ]

        usuarios_creados = {}
        for u_data in usuarios_data:
            user, created = Usuario.objects.get_or_create(
                username=u_data['username'],
                defaults={
                    'rut': u_data['rut'],
                    'first_name': u_data['first_name'],
                    'last_name': u_data['last_name'],
                    'email': u_data['email'],
                    'rol': u_data['rol'],
                    'is_staff': u_data['is_staff'],
                    'is_superuser': u_data['is_superuser'],
                    'pin_seguridad': u_data.get('pin_seguridad', ''),
                }
            )
            user.set_password('Inacap2026!')
            if u_data.get('pin_seguridad'):
                user.pin_seguridad = u_data['pin_seguridad']
            user.save()
            usuarios_creados[u_data['username']] = user
            self.stdout.write(f"  - Usuario {user.username} ({user.get_rol_display()}) OK")

        # ----------------------------------------------------
        # 2. MÉDICOS PRESCRIPTORES HABILITADOS
        # ----------------------------------------------------
        self.stdout.write("2. Creando médicos prescriptores habilitados...")
        medicos_data = [
            {
                'rut': '12.345.678-5',
                'nombres': 'Matías Ignacio',
                'apellido_paterno': 'Alarcón',
                'apellido_materno': 'Paredes',
                'especialidad': 'Medicina Familiar y Comunitaria',
                'registro_sis': 'MED-48291',
                'habilitado': True,
            },
            {
                'rut': '15.432.109-8',
                'nombres': 'Francisca Andrea',
                'apellido_paterno': 'Valenzuela',
                'apellido_materno': 'Tapia',
                'especialidad': 'Medicina General APS',
                'registro_sis': 'MED-61024',
                'habilitado': True,
            },
            {
                'rut': '10.876.543-7',
                'nombres': 'Jorge Hernán',
                'apellido_paterno': 'Silva',
                'apellido_materno': 'Morales',
                'especialidad': 'Medicina Interna',
                'registro_sis': 'MED-30588',
                'habilitado': True,
            },
        ]
        medicos_creados = []
        for m_data in medicos_data:
            med, _ = MedicoPrescriptor.objects.get_or_create(
                rut=m_data['rut'],
                defaults=m_data
            )
            medicos_creados.append(med)
            self.stdout.write(f"  - Dr(a). {med} OK")

        # ----------------------------------------------------
        # 3. PACIENTES FONASA CON RUT VÁLIDO (MÓDULO 11)
        # ----------------------------------------------------
        self.stdout.write("3. Creando pacientes beneficiarios FONASA/PRAIS...")
        pacientes_data = [
            {
                'rut': '11.234.567-1',
                'nombres': 'Juan Carlos',
                'apellido_paterno': 'Pérez',
                'apellido_materno': 'Soto',
                'fecha_nacimiento': date(1958, 4, 15),
                'sexo': 'M',
                'direccion': 'Av. Los Aromos 1240, La Florida',
                'telefono': '+56987654321',
                'email': 'juan.perez@correo.cl',
                'prevision': Paciente.Prevision.FONASA_A,
                'cronico': True,
            },
            {
                'rut': '8.765.432-K',
                'nombres': 'María Eugenia',
                'apellido_paterno': 'Morales',
                'apellido_materno': 'Castro',
                'fecha_nacimiento': date(1952, 9, 23),
                'sexo': 'F',
                'direccion': 'Pasaje Las Violetas 455, Puente Alto',
                'telefono': '+56976543210',
                'email': 'maria.morales@correo.cl',
                'prevision': Paciente.Prevision.FONASA_B,
                'cronico': True,
            },
            {
                'rut': '13.579.246-2',
                'nombres': 'Carlos Alberto',
                'apellido_paterno': 'Silva',
                'apellido_materno': 'Rojas',
                'fecha_nacimiento': date(1974, 2, 8),
                'sexo': 'M',
                'direccion': 'Calle San Martín 890, Santiago',
                'telefono': '+56965432109',
                'email': 'carlos.silva@correo.cl',
                'prevision': Paciente.Prevision.FONASA_C,
                'cronico': True,
            },
            {
                'rut': '9.876.543-3',
                'nombres': 'Ana Luisa',
                'apellido_paterno': 'Carrasco',
                'apellido_materno': 'Vera',
                'fecha_nacimiento': date(1963, 11, 30),
                'sexo': 'F',
                'direccion': 'Av. Central 312, Maipú',
                'telefono': '+56954321098',
                'email': 'ana.carrasco@correo.cl',
                'prevision': Paciente.Prevision.FONASA_D,
                'cronico': False,
            },
            {
                'rut': '7.654.321-6',
                'nombres': 'Pedro Alfonso',
                'apellido_paterno': 'Tapia',
                'apellido_materno': 'Vega',
                'fecha_nacimiento': date(1948, 6, 12),
                'sexo': 'M',
                'direccion': 'Calle Yungay 102, San Joaquín',
                'telefono': '+56943210987',
                'email': 'pedro.tapia@correo.cl',
                'prevision': Paciente.Prevision.PRAIS,
                'cronico': True,
            },
        ]
        pacientes_creados = []
        for p_data in pacientes_data:
            pac, _ = Paciente.objects.get_or_create(
                rut=p_data['rut'],
                defaults=p_data
            )
            pacientes_creados.append(pac)
            self.stdout.write(f"  - Paciente {pac.nombre_completo} ({pac.rut}) OK")

        # ----------------------------------------------------
        # 4. UBICACIONES FÍSICAS DE STOCK
        # ----------------------------------------------------
        self.stdout.write("4. Creando ubicaciones físicas...")
        bodega, _ = Ubicacion.objects.get_or_create(
            nombre='Bodega Central de Farmacia',
            defaults={
                'tipo': Ubicacion.TipoUbicacion.BODEGA,
                'descripcion': 'Almacén general y recepción de remesas CENABAST',
            }
        )
        vitrina, _ = Ubicacion.objects.get_or_create(
            nombre='Vitrina de Dispensación Mostrador',
            defaults={
                'tipo': Ubicacion.TipoUbicacion.VITRINA,
                'descripcion': 'Stock circulante para atención ambulatoria directa',
            }
        )

        # ----------------------------------------------------
        # 5. CATEGORÍAS Y MEDICAMENTOS DEL ARSENAL
        # ----------------------------------------------------
        self.stdout.write("5. Creando categorías y medicamentos del arsenal APS...")
        cat_cardio, _ = CategoriaMedicamento.objects.get_or_create(
            nombre='Cardiovascular / Antihipertensivos',
            defaults={'descripcion': 'Manejo de HTA en APS', 'es_controlado': False}
        )
        cat_metab, _ = CategoriaMedicamento.objects.get_or_create(
            nombre='Metabolismo / Antidiabéticos',
            defaults={'descripcion': 'Manejo de Diabetes Mellitus', 'es_controlado': False}
        )
        cat_analg, _ = CategoriaMedicamento.objects.get_or_create(
            nombre='Analgésicos y Antipiréticos',
            defaults={'descripcion': 'Alivio del dolor e inflamación', 'es_controlado': False}
        )
        cat_ctrl, _ = CategoriaMedicamento.objects.get_or_create(
            nombre='Psicotrópicos y Estupefacientes (D.S. 404/405)',
            defaults={'descripcion': 'Sujetos a control y libro foliado', 'es_controlado': True}
        )
        cat_urg, _ = CategoriaMedicamento.objects.get_or_create(
            nombre='Fármacos de Emergencia y Carro de Paro',
            defaults={'descripcion': 'Reanimación cardiopulmonar en box', 'es_controlado': False}
        )

        # Medicamento 1: Losartán (Demostración FEFO con 4 lotes)
        med_losartan, _ = Medicamento.objects.get_or_create(
            codigo='MED-CARD-001',
            defaults={
                'nombre_generico': 'Losartán Potásico',
                'nombre_comercial': 'Cozaar / Genérico CENABAST',
                'concentracion': '50 mg',
                'forma_farmaceutica': 'Comprimido recubierto',
                'unidad_medida': Medicamento.UnidadMedida.COMPRIMIDO,
                'categoria': cat_cardio,
                'stock_minimo': 100,
                'stock_maximo': 2000,
                'es_controlado': False,
            }
        )

        # Medicamento 2: Metformina (GES Diabetes)
        med_metformina, _ = Medicamento.objects.get_or_create(
            codigo='MED-MET-001',
            defaults={
                'nombre_generico': 'Metformina Clorhidrato',
                'nombre_comercial': 'Glucophage / Genérico CENABAST',
                'concentracion': '850 mg',
                'forma_farmaceutica': 'Comprimido',
                'unidad_medida': Medicamento.UnidadMedida.COMPRIMIDO,
                'categoria': cat_metab,
                'stock_minimo': 100,
                'stock_maximo': 2500,
                'es_controlado': False,
            }
        )

        # Medicamento 3: Paracetamol
        med_paracetamol, _ = Medicamento.objects.get_or_create(
            codigo='MED-ANAL-001',
            defaults={
                'nombre_generico': 'Paracetamol',
                'nombre_comercial': 'Tylenol / Kitadol',
                'concentracion': '500 mg',
                'forma_farmaceutica': 'Comprimido',
                'unidad_medida': Medicamento.UnidadMedida.COMPRIMIDO,
                'categoria': cat_analg,
                'stock_minimo': 50,
                'stock_maximo': 1500,
                'es_controlado': False,
            }
        )

        # Medicamento 4: Clonazepam (Psicotrópico D.S. 405)
        med_clonazepam, _ = Medicamento.objects.get_or_create(
            codigo='MED-CTRL-001',
            defaults={
                'nombre_generico': 'Clonazepam',
                'nombre_comercial': 'Rivotril / Ravotril',
                'concentracion': '2 mg',
                'forma_farmaceutica': 'Comprimido ranurado',
                'unidad_medida': Medicamento.UnidadMedida.COMPRIMIDO,
                'categoria': cat_ctrl,
                'stock_minimo': 30,
                'stock_maximo': 500,
                'es_controlado': True,
            }
        )

        # Medicamento 5: Morfina (Estupefaciente D.S. 404)
        med_morfina, _ = Medicamento.objects.get_or_create(
            codigo='MED-CTRL-002',
            defaults={
                'nombre_generico': 'Morfina Clorhidrato',
                'nombre_comercial': 'Morfina ISP',
                'concentracion': '10 mg/ml',
                'forma_farmaceutica': 'Ampolla inyectable 1 ml',
                'unidad_medida': Medicamento.UnidadMedida.AMPOLLA,
                'categoria': cat_ctrl,
                'stock_minimo': 20,
                'stock_maximo': 300,
                'es_controlado': True,
            }
        )

        # Medicamentos Carro de Paro: Adrenalina, Amiodarona, Atropina
        med_adrenalina, _ = Medicamento.objects.get_or_create(
            codigo='MED-URG-001',
            defaults={
                'nombre_generico': 'Adrenalina (Epinefrina)',
                'nombre_comercial': 'Adrenalina Biol',
                'concentracion': '1 mg/ml (1:1000)',
                'forma_farmaceutica': 'Ampolla 1 ml',
                'unidad_medida': Medicamento.UnidadMedida.AMPOLLA,
                'categoria': cat_urg,
                'stock_minimo': 20,
                'stock_maximo': 200,
                'es_controlado': False,
            }
        )
        med_amiodarona, _ = Medicamento.objects.get_or_create(
            codigo='MED-URG-002',
            defaults={
                'nombre_generico': 'Amiodarona Clorhidrato',
                'nombre_comercial': 'Atlansil',
                'concentracion': '150 mg/3ml',
                'forma_farmaceutica': 'Ampolla inyectable',
                'unidad_medida': Medicamento.UnidadMedida.AMPOLLA,
                'categoria': cat_urg,
                'stock_minimo': 15,
                'stock_maximo': 150,
                'es_controlado': False,
            }
        )
        med_atropina, _ = Medicamento.objects.get_or_create(
            codigo='MED-URG-003',
            defaults={
                'nombre_generico': 'Atropina Sulfato',
                'nombre_comercial': 'Atropina Sanderson',
                'concentracion': '1 mg/ml',
                'forma_farmaceutica': 'Ampolla 1 ml',
                'unidad_medida': Medicamento.UnidadMedida.AMPOLLA,
                'categoria': cat_urg,
                'stock_minimo': 20,
                'stock_maximo': 200,
                'es_controlado': False,
            }
        )

        # ----------------------------------------------------
        # 6. LOTES Y ALGORITMO FEFO (Multi-Lote)
        # ----------------------------------------------------
        self.stdout.write("6. Creando lotes para demostración del algoritmo FEFO...")

        # Losartán: 4 lotes diseñados para demostrar FEFO y bloqueo de vencido
        lotes_losartan = [
            {
                'numero_lote': 'LOS-2026-A1',
                'fecha_fabricacion': hoy - timedelta(days=340),
                'fecha_vencimiento': hoy + timedelta(days=20),  # Vence en 20 días (Próximo a vencer - FEFO First)
                'cantidad_inicial': 300,
                'cantidad_actual': 120,
                'ubicacion': vitrina,
                'proveedor': 'Laboratorio Chile / CENABAST',
            },
            {
                'numero_lote': 'LOS-2026-B2',
                'fecha_fabricacion': hoy - timedelta(days=200),
                'fecha_vencimiento': hoy + timedelta(days=75),  # Vence en 75 días
                'cantidad_inicial': 500,
                'cantidad_actual': 400,
                'ubicacion': vitrina,
                'proveedor': 'Laboratorio Chile / CENABAST',
            },
            {
                'numero_lote': 'LOS-2026-C3',
                'fecha_fabricacion': hoy - timedelta(days=50),
                'fecha_vencimiento': hoy + timedelta(days=360), # Vence en 360 días
                'cantidad_inicial': 800,
                'cantidad_actual': 800,
                'ubicacion': bodega,
                'proveedor': 'Laboratorio Chile / CENABAST',
            },
            {
                'numero_lote': 'LOS-2025-VENC',
                'fecha_fabricacion': hoy - timedelta(days=700),
                'fecha_vencimiento': hoy - timedelta(days=15),  # VENCIDO hace 15 días (Bloqueo)
                'cantidad_inicial': 100,
                'cantidad_actual': 30,
                'ubicacion': bodega,
                'proveedor': 'Laboratorio Saval',
            },
        ]
        for l_data in lotes_losartan:
            Lote.objects.get_or_create(
                medicamento=med_losartan,
                numero_lote=l_data['numero_lote'],
                ubicacion=l_data['ubicacion'],
                defaults=l_data
            )

        # Metformina: 2 lotes
        Lote.objects.get_or_create(
            medicamento=med_metformina,
            numero_lote='MET-2026-01',
            ubicacion=vitrina,
            defaults={
                'numero_lote': 'MET-2026-01',
                'fecha_fabricacion': hoy - timedelta(days=180),
                'fecha_vencimiento': hoy + timedelta(days=45),  # Vence en 45 días
                'cantidad_inicial': 600,
                'cantidad_actual': 250,
                'ubicacion': vitrina,
                'proveedor': 'CENABAST / Mintlab',
            }
        )
        Lote.objects.get_or_create(
            medicamento=med_metformina,
            numero_lote='MET-2026-02',
            ubicacion=bodega,
            defaults={
                'numero_lote': 'MET-2026-02',
                'fecha_fabricacion': hoy - timedelta(days=60),
                'fecha_vencimiento': hoy + timedelta(days=400),
                'cantidad_inicial': 1200,
                'cantidad_actual': 1200,
                'ubicacion': bodega,
                'proveedor': 'CENABAST / Mintlab',
            }
        )

        # Paracetamol: 2 lotes
        Lote.objects.get_or_create(
            medicamento=med_paracetamol,
            numero_lote='PAR-2026-01',
            ubicacion=vitrina,
            defaults={
                'numero_lote': 'PAR-2026-01',
                'fecha_fabricacion': hoy - timedelta(days=90),
                'fecha_vencimiento': hoy + timedelta(days=85),
                'cantidad_inicial': 800,
                'cantidad_actual': 350,
                'ubicacion': vitrina,
                'proveedor': 'Laboratorio Mintlab',
            }
        )

        # Clonazepam (Controlado): 1 lote
        lote_clona, _ = Lote.objects.get_or_create(
            medicamento=med_clonazepam,
            numero_lote='CLO-2026-01',
            ubicacion=vitrina,
            defaults={
                'numero_lote': 'CLO-2026-01',
                'fecha_fabricacion': hoy - timedelta(days=100),
                'fecha_vencimiento': hoy + timedelta(days=180),
                'cantidad_inicial': 200,
                'cantidad_actual': 80,
                'ubicacion': vitrina,
                'proveedor': 'Laboratorio Roche / CENABAST',
            }
        )

        # Morfina (Controlado): 1 lote
        lote_morfina, _ = Lote.objects.get_or_create(
            medicamento=med_morfina,
            numero_lote='MOR-2026-01',
            ubicacion=bodega,
            defaults={
                'numero_lote': 'MOR-2026-01',
                'fecha_fabricacion': hoy - timedelta(days=120),
                'fecha_vencimiento': hoy + timedelta(days=240),
                'cantidad_inicial': 100,
                'cantidad_actual': 45,
                'ubicacion': bodega,
                'proveedor': 'Laboratorio Sanderson ISP',
            }
        )

        # Urgencias: Adrenalina, Amiodarona, Atropina
        lote_adrena, _ = Lote.objects.get_or_create(
            medicamento=med_adrenalina,
            numero_lote='ADR-2026-01',
            ubicacion=bodega,
            defaults={
                'numero_lote': 'ADR-2026-01',
                'fecha_fabricacion': hoy - timedelta(days=60),
                'fecha_vencimiento': hoy + timedelta(days=280),
                'cantidad_inicial': 150,
                'cantidad_actual': 80,
                'ubicacion': bodega,
                'proveedor': 'Laboratorio Sanderson',
            }
        )
        lote_amioda, _ = Lote.objects.get_or_create(
            medicamento=med_amiodarona,
            numero_lote='AMI-2026-01',
            ubicacion=bodega,
            defaults={
                'numero_lote': 'AMI-2026-01',
                'fecha_fabricacion': hoy - timedelta(days=80),
                'fecha_vencimiento': hoy + timedelta(days=290),
                'cantidad_inicial': 100,
                'cantidad_actual': 60,
                'ubicacion': bodega,
                'proveedor': 'Laboratorio Sanderson',
            }
        )
        lote_atrop, _ = Lote.objects.get_or_create(
            medicamento=med_atropina,
            numero_lote='ATR-2026-01',
            ubicacion=bodega,
            defaults={
                'numero_lote': 'ATR-2026-01',
                'fecha_fabricacion': hoy - timedelta(days=90),
                'fecha_vencimiento': hoy + timedelta(days=310),
                'cantidad_inicial': 120,
                'cantidad_actual': 75,
                'ubicacion': bodega,
                'proveedor': 'Laboratorio Sanderson',
            }
        )

        # ----------------------------------------------------
        # 7. PROGRAMAS GES / AUGE Y CONTROL DE CUOTAS
        # ----------------------------------------------------
        self.stdout.write("7. Creando programas de salud GES/AUGE y canastas...")
        ges_hta, _ = PatologiaGES.objects.get_or_create(
            codigo='GES-01',
            defaults={
                'nombre': 'Hipertensión Arterial Primaria o Esencial en personas de 15 años y más',
                'descripcion': 'Garantía Explícita de Salud N° 21, tratamiento farmacológico continuo',
                'activa': True,
            }
        )
        ges_dm2, _ = PatologiaGES.objects.get_or_create(
            codigo='GES-02',
            defaults={
                'nombre': 'Diabetes Mellitus Tipo 2',
                'descripcion': 'Garantía Explícita de Salud N° 2, hipoglucemiantes orales e insulinas',
                'activa': True,
            }
        )

        canasta_losartan, _ = CanastaGES.objects.get_or_create(
            patologia=ges_hta,
            medicamento=med_losartan,
            defaults={
                'cantidad_por_cuota': 60,   # 60 comprimidos (tratamiento de 30 días a 50mg c/12h)
                'cuotas_autorizadas': 12,   # 12 cuotas anuales
            }
        )
        canasta_metformina, _ = CanastaGES.objects.get_or_create(
            patologia=ges_dm2,
            medicamento=med_metformina,
            defaults={
                'cantidad_por_cuota': 60,
                'cuotas_autorizadas': 12,
            }
        )

        # Inscripción del paciente Juan Pérez en GES Hipertensión
        paciente_juan = pacientes_creados[0]
        insc_juan_hta, _ = InscripcionGES.objects.get_or_create(
            paciente=paciente_juan,
            patologia=ges_hta,
            defaults={
                'fecha_inscripcion': hoy - timedelta(days=120),
                'fecha_inicio_periodo': hoy - timedelta(days=120),
                'fecha_fin_periodo': hoy + timedelta(days=245),
                'activa': True,
            }
        )
        # Cuotas previas de Juan Pérez (3 cuotas entregadas de 12)
        for i in range(1, 4):
            CuotaGES.objects.get_or_create(
                inscripcion=insc_juan_hta,
                canasta=canasta_losartan,
                numero_cuota=i,
                defaults={
                    'cantidad_entregada': 60,
                }
            )

        # Inscripción de María Morales en Diabetes Mellitus Tipo 2 (Con 12 cuotas entregadas -> AGOTADAS)
        paciente_maria = pacientes_creados[1]
        insc_maria_dm2, _ = InscripcionGES.objects.get_or_create(
            paciente=paciente_maria,
            patologia=ges_dm2,
            defaults={
                'fecha_inscripcion': hoy - timedelta(days=360),
                'fecha_inicio_periodo': hoy - timedelta(days=360),
                'fecha_fin_periodo': hoy + timedelta(days=5),
                'activa': True,
            }
        )
        for i in range(1, 13):
            CuotaGES.objects.get_or_create(
                inscripcion=insc_maria_dm2,
                canasta=canasta_metformina,
                numero_cuota=i,
                defaults={
                    'cantidad_entregada': 60,
                }
            )

        # ----------------------------------------------------
        # 8. CARRO DE PARO Y PLANTILLA CANÓNICA
        # ----------------------------------------------------
        self.stdout.write("8. Creando Carro de Paro de reanimación...")
        carro_paro, _ = CarroClinico.objects.get_or_create(
            nombre='Carro de Paro N° 1 - Reanimación Adulto',
            defaults={
                'tipo': CarroClinico.TipoCarro.PARO,
                'ubicacion_fisica': 'Box de Reanimación Cardiopulmonar (Urgencia APS)',
                'estado': CarroClinico.EstadoCarro.COMPLETO,
                'numero_precinto': 'PREC-2026-PARO-01',
                'fecha_ultimo_precinto': datetime.now(timezone.utc) - timedelta(days=3),
                'responsable_actual': usuarios_creados['enfermera_gonzalez'],
            }
        )

        item_adr, _ = PlantillaItemCarro.objects.get_or_create(
            carro=carro_paro,
            medicamento=med_adrenalina,
            defaults={
                'cantidad_requerida': 10,
                'cantidad_actual': 10,
                'ubicacion_en_carro': 'Cajón 1 - Medicamentos de Reanimación',
            }
        )
        item_ami, _ = PlantillaItemCarro.objects.get_or_create(
            carro=carro_paro,
            medicamento=med_amiodarona,
            defaults={
                'cantidad_requerida': 5,
                'cantidad_actual': 5,
                'ubicacion_en_carro': 'Cajón 1 - Antiarrítmicos',
            }
        )
        item_atr, _ = PlantillaItemCarro.objects.get_or_create(
            carro=carro_paro,
            medicamento=med_atropina,
            defaults={
                'cantidad_requerida': 10,
                'cantidad_actual': 10,
                'ubicacion_en_carro': 'Cajón 1 - Anticolinérgicos',
            }
        )

        # Carro de Unidosis de Sala
        carro_unidosis, _ = CarroClinico.objects.get_or_create(
            nombre='Carro de Tratamiento Unidosis - Box Procedimientos',
            defaults={
                'tipo': CarroClinico.TipoCarro.UNIDOSIS,
                'ubicacion_fisica': 'Sala de Curaciones y Tratamientos',
                'estado': CarroClinico.EstadoCarro.COMPLETO,
                'numero_precinto': 'PREC-2026-UNI-02',
                'fecha_ultimo_precinto': datetime.now(timezone.utc) - timedelta(days=1),
                'responsable_actual': usuarios_creados['enfermera_gonzalez'],
            }
        )

        # ----------------------------------------------------
        # 9. RECETAS MÉDICAS Y DISPENSACIÓN ASISTENCIAL GRATUITA
        # ----------------------------------------------------
        self.stdout.write("9. Creando recetas y dispensaciones con tercero autorizado ($0 copago)...")

        receta_juan, _ = Receta.objects.get_or_create(
            numero_receta='REC-2026-00101',
            defaults={
                'paciente': paciente_juan,
                'medico': medicos_creados[0],
                'tipo': Receta.TipoReceta.CRONICA,
                'estado': Receta.EstadoReceta.DISPENSADA_TOTAL,
                'diagnostico': 'Hipertensión Arterial Primaria I10 (GES 01)',
                'fecha_emision': hoy - timedelta(days=2),
                'fecha_vencimiento': hoy + timedelta(days=28),
                'observaciones': 'Tratamiento crónico mensual. Control en 6 meses.',
            }
        )
        det_receta_juan, _ = DetalleReceta.objects.get_or_create(
            receta=receta_juan,
            medicamento=med_losartan,
            defaults={
                'cantidad_prescrita': 60,
                'cantidad_dispensada': 60,
                'posologia': '1 comprimido cada 12 horas por vía oral',
                'dias_tratamiento': 30,
            }
        )

        # Tercero autorizado para Juan Pérez (su hija Carolina)
        tercero_carolina, _ = TerceroAutorizado.objects.get_or_create(
            rut='20.123.456-5',
            defaults={
                'nombres': 'Carolina Andrea',
                'apellido_paterno': 'Pérez',
                'apellido_materno': 'Soto',
                'parentesco': 'Hija / Cuidadora principal',
                'telefono': '+56988887777',
            }
        )

        dispensacion_juan, _ = Dispensacion.objects.get_or_create(
            receta=receta_juan,
            defaults={
                'usuario_dispensador': usuarios_creados['tecnico_alvarez'],
                'retiro_tercero': True,
                'tercero_autorizado': tercero_carolina,
                'copago': 0,  # $0 Copago estricto
                'observaciones': 'Retiro por hija con poder simple y cédula de identidad original.',
            }
        )

        # Lote seleccionado por FEFO
        lote_fefo_sugerido = med_losartan.lotes_fefo().first()
        if lote_fefo_sugerido:
            DetalleDispensacion.objects.get_or_create(
                dispensacion=dispensacion_juan,
                detalle_receta=det_receta_juan,
                lote=lote_fefo_sugerido,
                defaults={
                    'cantidad': 60,
                    'fefo_override': False,
                    'justificacion_override': '',
                }
            )

        # Receta pendiente para prueba directa de dispensación
        receta_pendiente, _ = Receta.objects.get_or_create(
            numero_receta='REC-2026-00102',
            defaults={
                'paciente': pacientes_creados[2], # Carlos Silva
                'medico': medicos_creados[1],     # Dra. Valenzuela
                'tipo': Receta.TipoReceta.SIMPLE,
                'estado': Receta.EstadoReceta.PENDIENTE,
                'diagnostico': 'Síndrome febril inespecífico / Cefalea tensional',
                'fecha_emision': hoy,
                'fecha_vencimiento': hoy + timedelta(days=15),
                'observaciones': 'Reposo por 48 horas y analgesia SOS.',
            }
        )
        DetalleReceta.objects.get_or_create(
            receta=receta_pendiente,
            medicamento=med_paracetamol,
            defaults={
                'cantidad_prescrita': 20,
                'cantidad_dispensada': 0,
                'posologia': '1 comprimido cada 8 horas por 5 días en caso de dolor o fiebre',
                'dias_tratamiento': 5,
            }
        )

        # ----------------------------------------------------
        # 10. LIBRO OFICIAL DIGITAL DE MEDICAMENTOS CONTROLADOS
        # ----------------------------------------------------
        self.stdout.write("10. Creando asientos foliados en Libro Oficial de Controlados...")
        asientos_ctrl = [
            {
                'folio': 1,
                'medicamento': med_clonazepam,
                'lote': lote_clona,
                'tipo_movimiento': LibroControlados.TipoMovimiento.INGRESO,
                'cantidad': 200,
                'saldo_anterior': 0,
                'saldo_posterior': 200,
                'quimico_responsable': usuarios_creados['qf_suazo'],
                'verificacion_2fa': True,
                'observaciones': 'Ingreso remesa CENABAST Guía Despacho N° 98402',
            },
            {
                'folio': 2,
                'medicamento': med_clonazepam,
                'lote': lote_clona,
                'tipo_movimiento': LibroControlados.TipoMovimiento.EGRESO,
                'cantidad': 120,
                'saldo_anterior': 200,
                'saldo_posterior': 80,
                'paciente': pacientes_creados[3],
                'quimico_responsable': usuarios_creados['qf_suazo'],
                'verificacion_2fa': True,
                'observaciones': 'Dispensación bajo Receta Cheque Oficial N° 449210-B',
            },
            {
                'folio': 3,
                'medicamento': med_morfina,
                'lote': lote_morfina,
                'tipo_movimiento': LibroControlados.TipoMovimiento.INGRESO,
                'cantidad': 100,
                'saldo_anterior': 0,
                'saldo_posterior': 100,
                'quimico_responsable': usuarios_creados['admin'],
                'verificacion_2fa': True,
                'observaciones': 'Recepción anual estupefacientes Resolución Sanitaria Seremi N° 2026/410',
            },
        ]
        for a_data in asientos_ctrl:
            LibroControlados.objects.get_or_create(
                folio=a_data['folio'],
                defaults=a_data
            )

        # ----------------------------------------------------
        # 11. AUDITORÍA INMUTABLE Y ALERTAS EN POSTGRESQL (JSONB)
        # ----------------------------------------------------
        self.stdout.write("11. Poblando tablas PostgreSQL de Auditoría Inmutable (JSONB) y Alertas...")
        if AuditoriaInmutable.objects.count() == 0:
            AuditoriaInmutable.objects.create(
                timestamp=datetime.now(timezone.utc) - timedelta(days=2),
                ip_origen='192.168.1.105',
                usuario=usuarios_creados['tecnico_alvarez'],
                usuario_username=usuarios_creados['tecnico_alvarez'].username,
                rol=usuarios_creados['tecnico_alvarez'].rol,
                accion='Dispensación asistencial gratuita ($0 Copago)',
                entidad_afectada='Dispensación #1 - Receta REC-2026-00101',
                valores_anteriores={'estado_receta': 'pendiente', 'copago': 0, 'stock_lote': 180},
                valores_nuevos={
                    'estado_receta': 'total',
                    'paciente': '11.234.567-1',
                    'tercero_rut': '20.123.456-5',
                    'lote_dispensado': 'LOS-2026-A1',
                    'cantidad': 60,
                    'stock_restante': 120,
                },
            )
            AuditoriaInmutable.objects.create(
                timestamp=datetime.now(timezone.utc) - timedelta(days=1),
                ip_origen='192.168.1.110',
                usuario=usuarios_creados['qf_suazo'],
                usuario_username=usuarios_creados['qf_suazo'].username,
                rol=usuarios_creados['qf_suazo'].rol,
                accion='Asiento en Libro Oficial Digital de Controlados (D.S. 404/405)',
                entidad_afectada='LibroControlados Folio #2',
                valores_anteriores={'saldo': 200},
                valores_nuevos={'saldo': 80, 'egreso': 120, '2fa_validado': True, 'receta_cheque': '449210-B'},
            )
            AuditoriaInmutable.objects.create(
                timestamp=datetime.now(timezone.utc) - timedelta(hours=5),
                ip_origen='192.168.1.115',
                usuario=usuarios_creados['qf_suazo'],
                usuario_username=usuarios_creados['qf_suazo'].username,
                rol=usuarios_creados['qf_suazo'].rol,
                accion='Advertencia de Override FEFO Autorizado',
                entidad_afectada='Lote LOS-2026-B2',
                valores_anteriores={'lote_fefo_sugerido': 'LOS-2026-A1'},
                valores_nuevos={
                    'lote_forzado': 'LOS-2026-B2',
                    'justificacion': 'Requerimiento de presentación en frasco sellado para paciente adulto mayor con movilidad reducida',
                },
            )
            AuditoriaInmutable.objects.create(
                timestamp=datetime.now(timezone.utc) - timedelta(hours=2),
                ip_origen='192.168.1.120',
                usuario=usuarios_creados['enfermera_gonzalez'],
                usuario_username=usuarios_creados['enfermera_gonzalez'].username,
                rol=usuarios_creados['enfermera_gonzalez'].rol,
                accion='Verificación y Precintado de Carro de Paro',
                entidad_afectada='Carro de Paro N° 1 - Reanimación Adulto',
                valores_anteriores={'estado': 'incompleto', 'precinto': 'PREC-2026-PARO-00'},
                valores_nuevos={'estado': 'completo', 'precinto': 'PREC-2026-PARO-01', 'dotacion': '100%'},
            )

        if AlertaSistema.objects.count() == 0:
            AlertaSistema.objects.create(
                tipo='vencimiento_critico',
                nivel='CRITICO',
                medicamento='Losartán Potásico 50 mg',
                lote='LOS-2026-A1',
                dias_restantes=20,
                ubicacion='Vitrina de Dispensación',
                mensaje='Vencimiento crítico en 20 días (<= 30 días). Prioridad FEFO inmediata.',
            )
            AlertaSistema.objects.create(
                tipo='vencimiento_medio',
                nivel='URGENTE',
                medicamento='Metformina Clorhidrato 850 mg',
                lote='MET-2026-01',
                dias_restantes=45,
                ubicacion='Vitrina de Dispensación',
                mensaje='Vencimiento próximo en 45 días (rango 31-60 días).',
            )
            AlertaSistema.objects.create(
                tipo='vencimiento_preventivo',
                nivel='PREVENTIVO',
                medicamento='Paracetamol 500 mg',
                lote='PAR-2026-01',
                dias_restantes=85,
                ubicacion='Vitrina de Dispensación',
                mensaje='Alerta preventiva de caducidad a 90 días.',
            )

        # Sincronización opcional secundaria si MongoDB está activo
        try:
            db = get_mongo_db()
            if db is not None:
                # a) Auditoría inmutable
                registros_auditoria = [
                    {
                        'timestamp': (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                        'ip_origen': '192.168.1.105',
                        'usuario_id': usuarios_creados['tecnico_alvarez'].id,
                        'usuario_username': usuarios_creados['tecnico_alvarez'].username,
                        'rol': usuarios_creados['tecnico_alvarez'].rol,
                        'accion': 'Dispensación asistencial gratuita',
                        'entidad_afectada': 'Dispensación #1 - Receta REC-2026-00101',
                        'valores_anteriores': {'estado_receta': 'pendiente', 'copago': 0},
                        'valores_nuevos': {
                            'estado_receta': 'total',
                            'paciente': '11.234.567-1',
                            'tercero_rut': '20.123.456-5',
                            'lote_dispensado': 'LOS-2026-A1',
                            'cantidad': 60,
                        },
                    },
                    {
                        'timestamp': (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
                        'ip_origen': '192.168.1.110',
                        'usuario_id': usuarios_creados['qf_suazo'].id,
                        'usuario_username': usuarios_creados['qf_suazo'].username,
                        'rol': usuarios_creados['qf_suazo'].rol,
                        'accion': 'Asiento en Libro Oficial Digital de Controlados',
                        'entidad_afectada': 'LibroControlados Folio #2',
                        'valores_anteriores': {'saldo': 200},
                        'valores_nuevos': {'saldo': 80, 'egreso': 120, '2fa_validado': True},
                    },
                    {
                        'timestamp': (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat(),
                        'ip_origen': '192.168.1.115',
                        'usuario_id': usuarios_creados['qf_suazo'].id,
                        'usuario_username': usuarios_creados['qf_suazo'].username,
                        'rol': usuarios_creados['qf_suazo'].rol,
                        'accion': 'Advertencia de Override FEFO',
                        'entidad_afectada': 'Lote LOS-2026-B2',
                        'valores_anteriores': {'lote_fefo_sugerido': 'LOS-2026-A1'},
                        'valores_nuevos': {
                            'lote_forzado': 'LOS-2026-B2',
                            'justificacion': 'Requerimiento de presentación en frasco sellado para paciente con movilidad reducida',
                        },
                    },
                ]
                db.auditoria_inmutable.insert_many(registros_auditoria)
                self.stdout.write("  - Colección 'auditoria_inmutable' poblada OK")

                # b) Recursos FHIR estandarizados (HL7 / FHIR R4)
                recursos_fhir = [
                    {
                        'resourceType': 'Patient',
                        'id': 'paciente-11234567-1',
                        'identifier': [
                            {
                                'use': 'official',
                                'system': 'urn:oid:2.16.152.1.2.1', # OID del Registro Civil Chile (RUN)
                                'value': '11.234.567-1'
                            }
                        ],
                        'name': [
                            {
                                'use': 'official',
                                'family': 'Pérez',
                                '_family': {'extension': [{'url': 'http://hl7.org/fhir/StructureDefinition/humanname-mothers-family', 'valueString': 'Soto'}]},
                                'given': ['Juan', 'Carlos']
                            }
                        ],
                        'gender': 'male',
                        'birthDate': '1958-04-15',
                        'telecom': [{'system': 'phone', 'value': '+56987654321', 'use': 'mobile'}],
                        'address': [{'use': 'home', 'line': ['Av. Los Aromos 1240'], 'city': 'La Florida', 'state': 'Metropolitana'}],
                    },
                    {
                        'resourceType': 'MedicationRequest',
                        'id': 'receta-2026-00101',
                        'status': 'completed',
                        'intent': 'order',
                        'subject': {'reference': 'Patient/paciente-11234567-1', 'display': 'Juan Carlos Pérez Soto'},
                        'medicationCodeableConcept': {
                            'coding': [
                                {
                                    'system': 'http://minsal.cl/farmaco/atc',
                                    'code': 'C09CA01',
                                    'display': 'Losartán Potásico 50 mg comprimido'
                                }
                            ]
                        },
                        'authoredOn': (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                        'requester': {'display': 'Dr. Matías Alarcón Paredes (SIS: MED-48291)'},
                        'dispenseRequest': {
                            'validityPeriod': {
                                'start': (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                                'end': (datetime.now(timezone.utc) + timedelta(days=28)).isoformat(),
                            },
                            'numberOfRepeatsAllowed': 1,
                            'quantity': {'value': 60, 'unit': 'comprimido'},
                        }
                    },
                    {
                        'resourceType': 'MedicationDispense',
                        'id': 'dispensacion-2026-00001',
                        'status': 'completed',
                        'medicationCodeableConcept': {
                            'coding': [{'system': 'http://minsal.cl/farmaco/atc', 'code': 'C09CA01', 'display': 'Losartán Potásico 50 mg'}]
                        },
                        'subject': {'reference': 'Patient/paciente-11234567-1'},
                        'authorizingPrescription': [{'reference': 'MedicationRequest/receta-2026-00101'}],
                        'performer': [{'actor': {'display': 'Rodrigo Álvarez Castro (Técnico en Farmacia)'}}],
                        'quantity': {'value': 60, 'unit': 'comprimido'},
                        'whenHandedOver': (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                        'note': [{'text': 'Retirado por tercero autorizado: Carolina Pérez Soto (RUT: 20.123.456-5)'}]
                    }
                ]
                db.recursos_fhir.insert_many(recursos_fhir)
                self.stdout.write("  - Colección 'recursos_fhir' poblada con esquemas HL7/FHIR OK")

                # c) Alertas del sistema (Vencimientos 30/60/90 días y quiebre de stock)
                alertas = [
                    {
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'tipo': 'vencimiento_critico',
                        'plazo_dias': 30,
                        'medicamento': 'Losartán Potásico 50 mg',
                        'lote': 'LOS-2026-A1',
                        'dias_restantes': 20,
                        'fecha_vencimiento': (hoy + timedelta(days=20)).isoformat(),
                        'ubicacion': 'Vitrina de Dispensación',
                        'nivel': 'CRITICO',
                        'leido': False,
                    },
                    {
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'tipo': 'vencimiento_medio',
                        'plazo_dias': 60,
                        'medicamento': 'Metformina Clorhidrato 850 mg',
                        'lote': 'MET-2026-01',
                        'dias_restantes': 45,
                        'fecha_vencimiento': (hoy + timedelta(days=45)).isoformat(),
                        'ubicacion': 'Vitrina de Dispensación',
                        'nivel': 'MEDIO',
                        'leido': False,
                    },
                    {
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'tipo': 'vencimiento_preventivo',
                        'plazo_dias': 90,
                        'medicamento': 'Paracetamol 500 mg',
                        'lote': 'PAR-2026-01',
                        'dias_restantes': 85,
                        'fecha_vencimiento': (hoy + timedelta(days=85)).isoformat(),
                        'ubicacion': 'Vitrina de Dispensación',
                        'nivel': 'PREVENTIVO',
                        'leido': False,
                    },
                    {
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'tipo': 'quiebre_stock',
                        'medicamento': 'Morfina Clorhidrato 10 mg/ml',
                        'stock_actual': 45,
                        'stock_minimo': 20,
                        'nivel': 'INFORMATIVO',
                        'mensaje': 'Stock cercano a umbral de reposición ministerial',
                        'leido': False,
                    }
                ]
                db.alertas_sistema.insert_many(alertas)
                self.stdout.write("  - Colección 'alertas_sistema' poblada con notificaciones OK")

        except Exception as e:
            self.stdout.write(self.style.WARNING(f"Aviso MongoDB: {e}"))

        self.stdout.write(self.style.SUCCESS("\n[EXITO] Base de datos relacional (PostgreSQL) y documental (MongoDB) pobladas correctamente."))
