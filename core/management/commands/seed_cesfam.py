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
from django.db.models import Q

from core.models import (
    SeccionCurso, Usuario, Paciente, MedicoPrescriptor, AuditoriaInmutable, AlertaSistema, EscenarioSimulacion
)
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

    def add_arguments(self, parser):
        parser.add_argument(
            '--preservar-usuarios',
            action='store_true',
            help='No sobrescribe contraseñas ni PINs de cuentas ya existentes en la base de datos.',
        )

    @transaction.atomic
    def handle(self, *args, **options):
        preservar_usuarios = bool(options.get('preservar_usuarios'))
        self.stdout.write(self.style.NOTICE("=== Iniciando Seed CESFAM Farmacia ==="))

        hoy = date.today()

        # ----------------------------------------------------
        # 1. USUARIOS (RBAC - 4 Roles) Y SECCIONES / CURSOS
        # ----------------------------------------------------
        self.stdout.write("1. Creando secciones y usuarios con RBAC...")

        secciones_base = [
            ('Docencia', 'Equipo docente y coordinación del simulador CESFAM'),
            ('AP-N4-C1', 'Sección base de simulación clínica INACAP'),
        ]
        for nom_sec, desc_sec in secciones_base:
            if not SeccionCurso.objects.filter(nombre__iexact=nom_sec).exists():
                SeccionCurso.objects.create(nombre=nom_sec, descripcion=desc_sec, activa=True)

        # PIN por defecto hasheado para 2FA
        pin_hash = make_password('123456')

        usuarios_data = [
            {
                'username': 'admin',
                'rut': '14.821.934-6',
                'first_name': 'Egon',
                'last_name': 'Muñoz Muttel',
                'email': 'egon.munoz@cesfam.cl',
                'seccion': 'Docencia',
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
                'seccion': 'AP-N4-C1',
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
                'seccion': 'AP-N4-C1',
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
                'seccion': 'AP-N4-C1',
                'rol': Usuario.Rol.PERSONAL_CLINICO,
                'is_staff': False,
                'is_superuser': False,
            },
        ]

        usuarios_creados = {}
        for u_data in usuarios_data:
            user = Usuario.objects.filter(
                Q(username=u_data['username']) | Q(rut=u_data['rut'])
            ).first()
            created = False
            if not user:
                user = Usuario.objects.create(
                    username=u_data['username'],
                    rut=u_data['rut'],
                    first_name=u_data['first_name'],
                    last_name=u_data['last_name'],
                    email=u_data['email'],
                    seccion=u_data.get('seccion', ''),
                    rol=u_data['rol'],
                    is_staff=u_data['is_staff'],
                    is_superuser=u_data['is_superuser'],
                    pin_seguridad=u_data.get('pin_seguridad', ''),
                )
                created = True
            elif not user.seccion and u_data.get('seccion'):
                user.seccion = u_data['seccion']
                user.save(update_fields=['seccion'])
            if created or not preservar_usuarios:
                user.set_password('Inacap2026!')
                if u_data.get('pin_seguridad'):
                    user.pin_seguridad = u_data['pin_seguridad']
                user.save()
            elif not user.has_usable_password():
                user.set_password('Inacap2026!')
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
        cat_resp, _ = CategoriaMedicamento.objects.get_or_create(
            nombre='Respiratorio / Broncodilatadores (GES Asma/EPOC)',
            defaults={'descripcion': 'Tratamiento de crisis bronquiales y asma/EPOC', 'es_controlado': False}
        )
        cat_resp_dup = CategoriaMedicamento.objects.filter(nombre='Respiratorio / Broncodilatadores').first()
        if cat_resp_dup:
            Medicamento.objects.filter(categoria=cat_resp_dup).update(categoria=cat_resp)
            cat_resp_dup.delete()
        cat_insumos, _ = CategoriaMedicamento.objects.get_or_create(
            nombre='Insumos Clínicos',
            defaults={'descripcion': 'Soluciones parenterales estériles y material clínico descartable APS', 'es_controlado': False}
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
        med_salbutamol, _ = Medicamento.objects.get_or_create(
            codigo='MED-RESP-001',
            defaults={
                'nombre_generico': 'Salbutamol Sulfato',
                'nombre_comercial': 'Aerolin / Genérico CENABAST',
                'concentracion': '100 mcg/dosis',
                'forma_farmaceutica': 'Inhalador presurizado (200 dosis)',
                'unidad_medida': Medicamento.UnidadMedida.INHALADOR,
                'categoria': cat_resp,
                'stock_minimo': 25,
                'stock_maximo': 300,
                'es_controlado': False,
            }
        )

        # Insumos Clínicos (RF-03)
        ins_suero, _ = Medicamento.objects.get_or_create(
            codigo='INS-CLI-001',
            defaults={
                'nombre_generico': 'Suero Fisiológico NaCl',
                'nombre_comercial': 'Cloruro de Sodio 0,9% Matraz / CENABAST',
                'concentracion': '0,9% (500 ml)',
                'forma_farmaceutica': 'Matraz solución estéril',
                'unidad_medida': Medicamento.UnidadMedida.FRASCO,
                'categoria': cat_insumos,
                'stock_minimo': 40,
                'stock_maximo': 600,
                'requiere_receta': False,
                'es_controlado': False,
            }
        )
        if ins_suero.nombre_generico != 'Suero Fisiológico NaCl' or ins_suero.concentracion != '0,9% (500 ml)':
            ins_suero.nombre_generico = 'Suero Fisiológico NaCl'
            ins_suero.concentracion = '0,9% (500 ml)'
            ins_suero.save(update_fields=['nombre_generico', 'concentracion'])
        ins_jeringa, _ = Medicamento.objects.get_or_create(
            codigo='INS-CLI-002',
            defaults={
                'nombre_generico': 'Jeringa Desechable 5 ml con aguja',
                'nombre_comercial': 'Jeringa Estéril 21G x 1½"',
                'concentracion': '5 ml (21G)',
                'forma_farmaceutica': 'Insumo estéril desechable',
                'unidad_medida': Medicamento.UnidadMedida.UNIDAD,
                'categoria': cat_insumos,
                'stock_minimo': 100,
                'stock_maximo': 2000,
                'requiere_receta': False,
                'es_controlado': False,
            }
        )

        # ----------------------------------------------------
        # 6. LOTES Y ALGORITMO FEFO (Multi-Lote)
        # ----------------------------------------------------
        self.stdout.write("6. Creando lotes para demostración del algoritmo FEFO...")

        # Losartán: 4 lotes diseñados para demostrar FEFO y bloqueo de vencido
        def registrar_kardex_inicial(lote):
            if not MovimientoStock.objects.filter(lote=lote).exists():
                MovimientoStock.objects.create(
                    lote=lote,
                    tipo=MovimientoStock.TipoMovimiento.INGRESO,
                    cantidad=lote.cantidad_inicial,
                    cantidad_anterior=0,
                    cantidad_posterior=lote.cantidad_inicial,
                    motivo=f'Ingreso inicial / Remesa CENABAST — Lote {lote.numero_lote}',
                    usuario=usuarios_creados['qf_suazo'],
                    ubicacion_destino=lote.ubicacion,
                )

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
            lote_obj, _ = Lote.objects.get_or_create(
                medicamento=med_losartan,
                numero_lote=l_data['numero_lote'],
                ubicacion=l_data['ubicacion'],
                defaults=l_data
            )
            registrar_kardex_inicial(lote_obj)

        # Metformina: 2 lotes
        lote_met_1, _ = Lote.objects.get_or_create(
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
        registrar_kardex_inicial(lote_met_1)
        lote_met_2, _ = Lote.objects.get_or_create(
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
        registrar_kardex_inicial(lote_met_2)

        # Paracetamol: 2 lotes
        lote_para_1, _ = Lote.objects.get_or_create(
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
        registrar_kardex_inicial(lote_para_1)

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
        registrar_kardex_inicial(lote_clona)

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
        registrar_kardex_inicial(lote_morfina)

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
        registrar_kardex_inicial(lote_adrena)
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
        registrar_kardex_inicial(lote_amioda)
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
        registrar_kardex_inicial(lote_atrop)
        lote_salbu, _ = Lote.objects.get_or_create(
            medicamento=med_salbutamol,
            numero_lote='SAL-2026-01',
            ubicacion=vitrina,
            defaults={
                'numero_lote': 'SAL-2026-01',
                'fecha_fabricacion': hoy - timedelta(days=45),
                'fecha_vencimiento': hoy + timedelta(days=360),
                'cantidad_inicial': 80,
                'cantidad_actual': 60,
                'ubicacion': vitrina,
                'proveedor': 'Laboratorio GSK / CENABAST',
            }
        )
        registrar_kardex_inicial(lote_salbu)

        # Lotes vigentes de Insumos Clínicos
        lote_suero_bod, _ = Lote.objects.get_or_create(
            medicamento=ins_suero,
            numero_lote='SUE-2026-01',
            ubicacion=bodega,
            defaults={
                'numero_lote': 'SUE-2026-01',
                'fecha_fabricacion': hoy - timedelta(days=40),
                'fecha_vencimiento': hoy + timedelta(days=540),
                'cantidad_inicial': 160,
                'cantidad_actual': 160,
                'ubicacion': bodega,
                'proveedor': 'CENABAST / B. Braun',
            }
        )
        registrar_kardex_inicial(lote_suero_bod)
        lote_suero_vit, _ = Lote.objects.get_or_create(
            medicamento=ins_suero,
            numero_lote='SUE-2026-01',
            ubicacion=vitrina,
            defaults={
                'numero_lote': 'SUE-2026-01',
                'fecha_fabricacion': hoy - timedelta(days=40),
                'fecha_vencimiento': hoy + timedelta(days=540),
                'cantidad_inicial': 40,
                'cantidad_actual': 40,
                'ubicacion': vitrina,
                'proveedor': 'CENABAST / B. Braun',
            }
        )
        registrar_kardex_inicial(lote_suero_vit)
        lote_jeringa_bod, _ = Lote.objects.get_or_create(
            medicamento=ins_jeringa,
            numero_lote='JER-2026-01',
            ubicacion=bodega,
            defaults={
                'numero_lote': 'JER-2026-01',
                'fecha_fabricacion': hoy - timedelta(days=30),
                'fecha_vencimiento': hoy + timedelta(days=720),
                'cantidad_inicial': 300,
                'cantidad_actual': 300,
                'ubicacion': bodega,
                'proveedor': 'CENABAST / Terumo',
            }
        )
        registrar_kardex_inicial(lote_jeringa_bod)
        lote_jeringa_vit, _ = Lote.objects.get_or_create(
            medicamento=ins_jeringa,
            numero_lote='JER-2026-01',
            ubicacion=vitrina,
            defaults={
                'numero_lote': 'JER-2026-01',
                'fecha_fabricacion': hoy - timedelta(days=30),
                'fecha_vencimiento': hoy + timedelta(days=720),
                'cantidad_inicial': 100,
                'cantidad_actual': 100,
                'ubicacion': vitrina,
                'proveedor': 'CENABAST / Terumo',
            }
        )
        registrar_kardex_inicial(lote_jeringa_vit)

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
        ges_epoc, _ = PatologiaGES.objects.get_or_create(
            codigo='GES-38',
            defaults={
                'nombre': 'Enfermedad Pulmonar Obstructiva Crónica (EPOC)',
                'descripcion': 'Garantía Explícita de Salud N° 38, tratamiento inhalatorio ambulatorio APS',
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
        canasta_salbutamol, _ = CanastaGES.objects.get_or_create(
            patologia=ges_epoc,
            medicamento=med_salbutamol,
            defaults={
                'cantidad_por_cuota': 2,
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

        # Inscripción de Pedro Alfonso Tapia Vega en GES EPOC (coherente con su receta de Salbutamol)
        paciente_pedro = pacientes_creados[4]
        InscripcionGES.objects.get_or_create(
            paciente=paciente_pedro,
            patologia=ges_epoc,
            defaults={
                'fecha_inscripcion': hoy - timedelta(days=90),
                'fecha_inicio_periodo': hoy - timedelta(days=90),
                'fecha_fin_periodo': hoy + timedelta(days=275),
                'activa': True,
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

        # Consumo de prueba registrado por Personal Clínico -> Carro de Paro parte con faltante = 2
        if not ConsumoCarroClinico.objects.filter(carro=carro_paro).exists() and not ReposicionCarro.objects.filter(carro=carro_paro).exists():
            ConsumoCarroClinico.objects.create(
                carro=carro_paro,
                item=item_adr,
                cantidad_consumida=2,
                motivo='Atención urgencia Box Reanimación (shock anafiláctico)',
                paciente_atendido='Juan Carlos Pérez Soto (11.234.567-1)',
                personal_clinico=usuarios_creados['enfermera_gonzalez'],
            )
            item_adr.cantidad_actual = max(0, item_adr.cantidad_requerida - 2)
            item_adr.save(update_fields=['cantidad_actual'])
            carro_paro.estado = CarroClinico.EstadoCarro.INCOMPLETO
            carro_paro.save(update_fields=['estado'])

        # Carro de Unidosis de Sala con dotación base realista (4 ítems)
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
        PlantillaItemCarro.objects.get_or_create(
            carro=carro_unidosis,
            medicamento=med_paracetamol,
            defaults={
                'cantidad_requerida': 20,
                'cantidad_actual': 20,
                'ubicacion_en_carro': 'Cajón 1 - Analgesia y Antipiresis',
            }
        )
        PlantillaItemCarro.objects.get_or_create(
            carro=carro_unidosis,
            medicamento=med_salbutamol,
            defaults={
                'cantidad_requerida': 4,
                'cantidad_actual': 4,
                'ubicacion_en_carro': 'Bandeja Respiratoria - Broncodilatadores',
            }
        )
        PlantillaItemCarro.objects.get_or_create(
            carro=carro_unidosis,
            medicamento=med_losartan,
            defaults={
                'cantidad_requerida': 15,
                'cantidad_actual': 15,
                'ubicacion_en_carro': 'Bandeja 2 - Control Cardiovascular',
            }
        )
        PlantillaItemCarro.objects.get_or_create(
            carro=carro_unidosis,
            medicamento=med_atropina,
            defaults={
                'cantidad_requerida': 5,
                'cantidad_actual': 5,
                'ubicacion_en_carro': 'Cajón Procedimientos - Ampollas',
            }
        )
        carro_unidosis.estado = (
            CarroClinico.EstadoCarro.COMPLETO
            if carro_unidosis.esta_completo
            else CarroClinico.EstadoCarro.INCOMPLETO
        )
        carro_unidosis.save(update_fields=['estado'])

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

        # Receta vencida de demostración (bloqueada en ventanilla)
        receta_vencida_demo, _ = Receta.objects.get_or_create(
            numero_receta='REC-2026-00102',
            defaults={
                'paciente': pacientes_creados[2], # Carlos Silva
                'medico': medicos_creados[1],     # Dra. Valenzuela
                'tipo': Receta.TipoReceta.SIMPLE,
                'estado': Receta.EstadoReceta.PENDIENTE,
                'diagnostico': 'Síndrome febril inespecífico / Cefalea tensional',
                'fecha_emision': hoy - timedelta(days=33),
                'fecha_vencimiento': hoy - timedelta(days=18),
                'observaciones': 'Reposo por 48 horas y analgesia SOS.',
            }
        )
        DetalleReceta.objects.get_or_create(
            receta=receta_vencida_demo,
            medicamento=med_paracetamol,
            defaults={
                'cantidad_prescrita': 20,
                'cantidad_dispensada': 0,
                'posologia': '1 comprimido cada 8 horas por 5 días en caso de dolor o fiebre',
                'dias_tratamiento': 5,
            }
        )

        # Receta simple vigente lista para atención directa en ventanilla
        receta_vigente_demo, _ = Receta.objects.get_or_create(
            numero_receta='REC-2026-00103',
            defaults={
                'paciente': pacientes_creados[2], # Carlos Silva
                'medico': medicos_creados[1],     # Dra. Valenzuela
                'tipo': Receta.TipoReceta.SIMPLE,
                'estado': Receta.EstadoReceta.PENDIENTE,
                'diagnostico': 'Control sintomático respiratorio y analgesia',
                'fecha_emision': hoy,
                'fecha_vencimiento': hoy + timedelta(days=15),
                'observaciones': 'Receta simple vigente para entrega inmediata en ventanilla.',
            }
        )
        DetalleReceta.objects.get_or_create(
            receta=receta_vigente_demo,
            medicamento=med_paracetamol,
            defaults={
                'cantidad_prescrita': 20,
                'cantidad_dispensada': 0,
                'posologia': '1 comprimido cada 8 horas si presenta dolor o fiebre',
                'dias_tratamiento': 7,
            }
        )

        # Receta Retenida / Controlada pendiente de autorización del Q.F.
        receta_ctrl_demo, _ = Receta.objects.get_or_create(
            numero_receta='REC-2026-00104',
            defaults={
                'paciente': pacientes_creados[3], # Ana Luisa Carrasco
                'medico': medicos_creados[0],     # Dr. Alarcón
                'tipo': Receta.TipoReceta.RETENIDA,
                'estado': Receta.EstadoReceta.PENDIENTE,
                'diagnostico': 'Trastorno de ansiedad generalizada en control APS',
                'fecha_emision': hoy,
                'fecha_vencimiento': hoy + timedelta(days=30),
                'autorizada_qf': False,
                'observaciones': 'Receta retenida de psicotrópico. Requiere visación del Químico Farmacéutico antes de entrega.',
            }
        )
        DetalleReceta.objects.get_or_create(
            receta=receta_ctrl_demo,
            medicamento=med_clonazepam,
            defaults={
                'cantidad_prescrita': 30,
                'cantidad_dispensada': 0,
                'posologia': '1 comprimido por la noche antes de dormir',
                'dias_tratamiento': 30,
            }
        )

        # Receta vigente de inhalador broncodilatador lista para entrega en ventanilla
        receta_salb_demo, _ = Receta.objects.get_or_create(
            numero_receta='REC-2026-00105',
            defaults={
                'paciente': pacientes_creados[4], # Pedro Alfonso Tapia Vega
                'medico': medicos_creados[2],     # Dr. Jorge Silva
                'tipo': Receta.TipoReceta.SIMPLE,
                'estado': Receta.EstadoReceta.PENDIENTE,
                'diagnostico': 'EPOC estable en control ambulatorio APS',
                'fecha_emision': hoy,
                'fecha_vencimiento': hoy + timedelta(days=15),
                'observaciones': 'Usar 2 puff cada 8 horas en caso de disnea.',
            }
        )
        DetalleReceta.objects.get_or_create(
            receta=receta_salb_demo,
            medicamento=med_salbutamol,
            defaults={
                'cantidad_prescrita': 2,
                'cantidad_dispensada': 0,
                'posologia': '2 inhalaciones cada 8 horas',
                'dias_tratamiento': 30,
            }
        )

        # Asegurar que recetas de prueba con fármacos simples (ej. Paracetamol) no queden marcadas como retenidas/controladas
        for rec_simple_check in Receta.objects.filter(tipo__in=[Receta.TipoReceta.RETENIDA, Receta.TipoReceta.CHEQUE]):
            if rec_simple_check.detalles.exists() and not rec_simple_check.tiene_medicamento_controlado:
                rec_simple_check.tipo = Receta.TipoReceta.SIMPLE
                rec_simple_check.save(update_fields=['tipo'])

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
                'quimico_responsable': usuarios_creados['qf_suazo'],
                'verificacion_2fa': True,
                'observaciones': 'Recepción anual estupefacientes Resolución Sanitaria Seremi N° 2026/410',
            },
        ]
        for a_data in asientos_ctrl:
            asiento_obj, _ = LibroControlados.objects.get_or_create(
                folio=a_data['folio'],
                defaults=a_data
            )
            if asiento_obj.folio == 3 and asiento_obj.quimico_responsable_id != usuarios_creados['qf_suazo'].pk:
                asiento_obj.quimico_responsable = usuarios_creados['qf_suazo']
                asiento_obj.save(update_fields=['quimico_responsable'])

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

        # 12. Escenarios de Simulación Docente (Evaluaciones / Talleres)
        self.stdout.write("12. Creando escenarios de simulación docente...")
        admin_seed = usuarios_creados.get('admin') or Usuario.objects.filter(rol=Usuario.Rol.ADMINISTRADOR).first()
        hay_activo = EscenarioSimulacion.objects.filter(activo=True).exists()

        # Pacientes y recetas exclusivas del escenario "Demo Integral — Evaluación Total CESFAM" (idempotente)
        demo_ruts = [
            '17.482.910-1',
            '6.482.915-7',
            '15.928.374-7',
            '9.234.817-2',
        ]
        demo_recetas_nums = [
            'REC-DEMO-001',
            'REC-DEMO-002',
            'REC-DEMO-003',
            'REC-DEMO-004',
        ]

        esc_base, _ = EscenarioSimulacion.objects.get_or_create(
            nombre='Escenario Base — Operación General CESFAM',
            defaults={
                'descripcion': 'Operación general completa del CESFAM con todo el padrón de pacientes y recetas disponibles.',
                'activo': not hay_activo,
                'creado_por': admin_seed,
            },
        )
        esc_base.pacientes.set(Paciente.objects.exclude(rut__in=demo_ruts))
        esc_base.recetas.set(Receta.objects.exclude(numero_receta__in=demo_recetas_nums))

        esc_eval, _ = EscenarioSimulacion.objects.get_or_create(
            nombre='Evaluación 1 — Crónicos GES y Controlados ISP',
            defaults={
                'descripcion': 'Taller evaluado focalizado en 3 pacientes (crónicos GES + controlados ISP) y 2 recetas activas para evaluación práctica.',
                'activo': False,
                'creado_por': admin_seed,
            },
        )
        pacientes_eval = list(
            Paciente.objects.filter(rut__in=['8.765.432-K', '7.654.321-6', '9.876.543-3'])
        )
        if not pacientes_eval:
            pacientes_eval = list(Paciente.objects.filter(cronico=True).exclude(rut__in=demo_ruts).order_by('id')[:3])
        recetas_eval = list(
            Receta.objects.filter(numero_receta__in=['REC-2026-00104', 'REC-2026-00105'])
        )
        if not recetas_eval:
            recetas_eval = list(
                Receta.objects.filter(paciente_id__in=[p.id for p in pacientes_eval]).order_by('-id')[:2]
            )
        esc_eval.pacientes.set(pacientes_eval)
        esc_eval.recetas.set(recetas_eval)

        # ----------------------------------------------------
        # 12B. ESCENARIO COMPLETO: DEMO INTEGRAL — EVALUACIÓN TOTAL CESFAM
        # ----------------------------------------------------
        self.stdout.write("12B. Configurando escenario 'Demo Integral — Evaluación Total CESFAM'...")

        # 4 Pacientes propios de este escenario
        pac_demo_1, _ = Paciente.objects.get_or_create(
            rut='17.482.910-1',
            defaults={
                'nombres': 'Valentina Paz',
                'apellido_paterno': 'Muñoz',
                'apellido_materno': 'Contreras',
                'fecha_nacimiento': date(1991, 5, 18),
                'sexo': 'F',
                'direccion': 'Av. Vicuña Mackenna 4820, Macul',
                'telefono': '+56971234501',
                'email': 'valentina.munoz@correo.cl',
                'prevision': Paciente.Prevision.FONASA_B,
                'cronico': False,
            },
        )

        pac_demo_2, _ = Paciente.objects.get_or_create(
            rut='6.482.915-7',
            defaults={
                'nombres': 'Héctor Manuel',
                'apellido_paterno': 'Riquelme',
                'apellido_materno': 'Araya',
                'fecha_nacimiento': date(1951, 9, 12),
                'sexo': 'M',
                'direccion': 'Pasaje Las Magnolias 215, La Florida',
                'telefono': '+56971234502',
                'email': 'hector.riquelme@correo.cl',
                'prevision': Paciente.Prevision.FONASA_A,
                'cronico': True,
                'tercero_autorizado_nombre': 'Javiera Constanza Riquelme Morales',
                'tercero_autorizado_rut': '18.654.321-1',
                'tercero_autorizado_parentesco': 'Hija / Cuidadora autorizada',
            },
        )
        # Asegurar datos de tercero autorizado en re-ejecuciones idempotentes
        if not pac_demo_2.tercero_autorizado_rut:
            pac_demo_2.tercero_autorizado_nombre = 'Javiera Constanza Riquelme Morales'
            pac_demo_2.tercero_autorizado_rut = '18.654.321-1'
            pac_demo_2.tercero_autorizado_parentesco = 'Hija / Cuidadora autorizada'
            pac_demo_2.save(update_fields=[
                'tercero_autorizado_nombre',
                'tercero_autorizado_rut',
                'tercero_autorizado_parentesco',
            ])
        TerceroAutorizado.objects.get_or_create(
            rut='18.654.321-1',
            defaults={
                'nombres': 'Javiera Constanza',
                'apellido_paterno': 'Riquelme',
                'apellido_materno': 'Morales',
                'parentesco': 'Hija / Cuidadora autorizada',
                'telefono': '+56981112233',
            },
        )
        insc_demo_hta, _ = InscripcionGES.objects.get_or_create(
            paciente=pac_demo_2,
            patologia=ges_hta,
            defaults={
                'fecha_inscripcion': hoy - timedelta(days=60),
                'fecha_inicio_periodo': hoy - timedelta(days=60),
                'fecha_fin_periodo': hoy + timedelta(days=305),
                'activa': True,
            },
        )
        for cuota_n in range(1, 3):
            CuotaGES.objects.get_or_create(
                inscripcion=insc_demo_hta,
                canasta=canasta_losartan,
                numero_cuota=cuota_n,
                defaults={'cantidad_entregada': 30},
            )

        pac_demo_3, _ = Paciente.objects.get_or_create(
            rut='15.928.374-7',
            defaults={
                'nombres': 'Diego Ignacio',
                'apellido_paterno': 'Fuentes',
                'apellido_materno': 'Salgado',
                'fecha_nacimiento': date(1984, 3, 27),
                'sexo': 'M',
                'direccion': 'Av. Irarrázaval 3190, Ñuñoa',
                'telefono': '+56971234503',
                'email': 'diego.fuentes@correo.cl',
                'prevision': Paciente.Prevision.FONASA_D,
                'cronico': False,
            },
        )

        pac_demo_4, _ = Paciente.objects.get_or_create(
            rut='9.234.817-2',
            defaults={
                'nombres': 'Rosa Elena',
                'apellido_paterno': 'Contreras',
                'apellido_materno': 'Valdés',
                'fecha_nacimiento': date(1956, 11, 4),
                'sexo': 'F',
                'direccion': 'Calle Santa Rosa 5412, San Joaquín',
                'telefono': '+56971234504',
                'email': 'rosa.contreras@correo.cl',
                'prevision': Paciente.Prevision.PRAIS,
                'cronico': True,
            },
        )
        insc_demo_epoc, _ = InscripcionGES.objects.get_or_create(
            paciente=pac_demo_4,
            patologia=ges_epoc,
            defaults={
                'fecha_inscripcion': hoy - timedelta(days=90),
                'fecha_inicio_periodo': hoy - timedelta(days=90),
                'fecha_fin_periodo': hoy + timedelta(days=275),
                'activa': True,
            },
        )
        CuotaGES.objects.get_or_create(
            inscripcion=insc_demo_epoc,
            canasta=canasta_salbutamol,
            numero_cuota=1,
            defaults={'cantidad_entregada': 2},
        )

        # 4 Recetas que cubren todos los casos (Simple, Crónica GES + Tercero, Controlada pendiente Q.F., Vencida -10d)
        rec_demo_a, _ = Receta.objects.get_or_create(
            numero_receta='REC-DEMO-001',
            defaults={
                'paciente': pac_demo_1,
                'medico': medicos_creados[1],
                'tipo': Receta.TipoReceta.SIMPLE,
                'estado': Receta.EstadoReceta.PENDIENTE,
                'diagnostico': 'Cefalea tensional y cuadro febril leve en atención APS',
                'fecha_emision': hoy,
                'fecha_vencimiento': hoy + timedelta(days=15),
                'observaciones': 'Receta simple vigente lista para dispensación FEFO e impresión de comprobante formal INACAP.',
            },
        )
        DetalleReceta.objects.get_or_create(
            receta=rec_demo_a,
            medicamento=med_paracetamol,
            defaults={
                'cantidad_prescrita': 20,
                'cantidad_dispensada': 0,
                'posologia': '1 comprimido cada 8 horas por vía oral en caso de dolor o fiebre',
                'dias_tratamiento': 7,
            },
        )

        rec_demo_b, _ = Receta.objects.get_or_create(
            numero_receta='REC-DEMO-002',
            defaults={
                'paciente': pac_demo_2,
                'medico': medicos_creados[0],
                'tipo': Receta.TipoReceta.CRONICA,
                'estado': Receta.EstadoReceta.PENDIENTE,
                'diagnostico': 'Hipertensión Arterial Esencial I10 (GES-01) — Retiro por tercero autorizado',
                'fecha_emision': hoy,
                'fecha_vencimiento': hoy + timedelta(days=30),
                'observaciones': 'Paciente adulto mayor crónico GES-01. Retiro autorizado a hija Javiera Riquelme (RUT 18.654.321-1).',
            },
        )
        DetalleReceta.objects.get_or_create(
            receta=rec_demo_b,
            medicamento=med_losartan,
            defaults={
                'cantidad_prescrita': 30,
                'cantidad_dispensada': 0,
                'posologia': '1 comprimido cada 24 horas por vía oral en la mañana',
                'dias_tratamiento': 30,
            },
        )

        rec_demo_c, _ = Receta.objects.get_or_create(
            numero_receta='REC-DEMO-003',
            defaults={
                'paciente': pac_demo_3,
                'medico': medicos_creados[0],
                'tipo': Receta.TipoReceta.RETENIDA,
                'estado': Receta.EstadoReceta.PENDIENTE,
                'diagnostico': 'Trastorno de ansiedad generalizada en control APS (Psicotrópico D.S. 405)',
                'fecha_emision': hoy,
                'fecha_vencimiento': hoy + timedelta(days=30),
                'autorizada_qf': False,
                'observaciones': 'Receta retenida sin visación previa del Q.F. Requiere autorización del Químico Farmacéutico y registro foliado ISP.',
            },
        )
        DetalleReceta.objects.get_or_create(
            receta=rec_demo_c,
            medicamento=med_clonazepam,
            defaults={
                'cantidad_prescrita': 30,
                'cantidad_dispensada': 0,
                'posologia': '1 comprimido por la noche antes de dormir',
                'dias_tratamiento': 30,
            },
        )

        rec_demo_d, _ = Receta.objects.get_or_create(
            numero_receta='REC-DEMO-004',
            defaults={
                'paciente': pac_demo_4,
                'medico': medicos_creados[2],
                'tipo': Receta.TipoReceta.SIMPLE,
                'estado': Receta.EstadoReceta.PENDIENTE,
                'diagnostico': 'EPOC estable en seguimiento ambulatorio (GES-38) — Receta fuera de vigencia',
                'fecha_emision': hoy - timedelta(days=40),
                'fecha_vencimiento': hoy - timedelta(days=10),
                'observaciones': 'Caso trampa: receta vencida hace 10 días para verificar bloqueo automático de vigencia.',
            },
        )
        DetalleReceta.objects.get_or_create(
            receta=rec_demo_d,
            medicamento=med_salbutamol,
            defaults={
                'cantidad_prescrita': 2,
                'cantidad_dispensada': 0,
                'posologia': '2 inhalaciones cada 8 horas según necesidad respiratoria',
                'dias_tratamiento': 30,
            },
        )

        consigna_demo_integral = (
            "Evaluación Integral CESFAM — Complete las 5 tareas en orden:\n"
            "1. Dispensación estándar y crónica GES: Entregue la receta simple de Paracetamol (Valentina Muñoz) bajo FEFO e imprima el documento formal; luego dispense Losartán GES-01 (Héctor Riquelme) registrando el retiro por su Tercero Autorizado (Javiera Riquelme, 18.654.321-1).\n"
            "2. Controlados ISP (D.S. 405): Verifique el bloqueo de Clonazepam (Diego Fuentes) como Técnico y luego autorice/dispense como Químico Farmacéutico comprobando el asiento automático en el Libro Foliado.\n"
            "3. Control de vigencia (Caso Trampa): Verifique el rechazo automático de la receta vencida de Salbutamol (Rosa Contreras, PRAIS · GES-38).\n"
            "4. Abastecimiento CENABAST y FEFO/Cuarentena: Atienda el quiebre de stock de Salbutamol (Técnico propone → Q.F. aprueba → Técnico recepciona en Bodega) y ejecute la baja a cuarentena del lote vencido en Vitrina con Q.F.\n"
            "5. Carros Clínicos: Reponga por FEFO las 2 ampollas de Adrenalina consumidas en el Carro de Paro (Precinto Roto) y registre el nuevo número de precinto."
        )

        esc_demo, creado_demo = EscenarioSimulacion.objects.get_or_create(
            nombre='Demo Integral — Evaluación Total CESFAM',
            defaults={
                'descripcion': (
                    'Escenario integral punta a punta con 4 pacientes dedicados (Simple FONASA B, Crónico GES-01 con '
                    'Tercero Autorizado, Controlado ISP y PRAIS GES-38 con receta vencida), 4 recetas y 3 incidencias '
                    'automáticas (quiebre Salbutamol, lote crítico FEFO + vencido en vitrina y consumo en Carro de Paro).'
                ),
                'modalidad': EscenarioSimulacion.Modalidad.INCIDENCIAS,
                'consignas_personalizadas': consigna_demo_integral,
                'mostrar_consigna_a_estudiantes': True,
                'simular_quiebre': True,
                'medicamento_quiebre': med_salbutamol,
                'simular_alerta_fefo': True,
                'simular_consumo_carro': True,
                'activo': False,
                'creado_por': admin_seed,
            },
        )
        if not creado_demo:
            esc_demo.modalidad = EscenarioSimulacion.Modalidad.INCIDENCIAS
            esc_demo.consignas_personalizadas = consigna_demo_integral
            esc_demo.mostrar_consigna_a_estudiantes = True
            esc_demo.simular_quiebre = True
            esc_demo.medicamento_quiebre = med_salbutamol
            esc_demo.simular_alerta_fefo = True
            esc_demo.simular_consumo_carro = True
            esc_demo.save(update_fields=[
                'modalidad',
                'consignas_personalizadas',
                'mostrar_consigna_a_estudiantes',
                'simular_quiebre',
                'medicamento_quiebre',
                'simular_alerta_fefo',
                'simular_consumo_carro',
            ])
        esc_demo.pacientes.set([pac_demo_1, pac_demo_2, pac_demo_3, pac_demo_4])
        esc_demo.recetas.set([rec_demo_a, rec_demo_b, rec_demo_c, rec_demo_d])

        self.stdout.write(self.style.SUCCESS("\n[EXITO] Base de datos relacional (PostgreSQL) y documental (MongoDB) pobladas correctamente."))
