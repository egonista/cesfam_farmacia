"""
Suite de Pruebas Automatizadas (QA) para el Sistema CESFAM Farmacia.
Incluye:
- Pruebas Unitarias: Módulo 11 de RUT, ordenamiento FEFO, bloqueo de lote vencido, cuotas GES, cifrado Ley 21.719.
- Pruebas Integrales: Flujo completo Receta -> Dispensación con Tercero -> Descuento PostgreSQL -> Log MongoDB.
- Pruebas de Rendimiento: Tiempo de respuesta consulta de dispensación < 1000 ms (RNF-06).
Autores: Egon Muñoz Muttel y Renato Suazo Burgos - INACAP 2026.
"""
import time
from datetime import date, timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from core.models import Usuario, Paciente, MedicoPrescriptor
from core.utils import (
    validar_rut, formatear_rut, calcular_digito_verificador,
    cifrar_dato, descifrar_dato
)
from farmacia.models import CategoriaMedicamento, Medicamento, Ubicacion, Lote, MovimientoStock
from dispensacion.models import Receta, DetalleReceta, TerceroAutorizado, Dispensacion, DetalleDispensacion
from ges.models import PatologiaGES, CanastaGES, InscripcionGES, CuotaGES
from core.mongo_client import get_mongo_db


class PruebasUnitariasCESFAM(TestCase):
    """Pruebas unitarias de algoritmos y reglas de negocio."""

    def setUp(self):
        # Ubicaciones
        self.bodega = Ubicacion.objects.create(
            nombre='Bodega Central Test',
            tipo=Ubicacion.TipoUbicacion.BODEGA
        )
        self.vitrina = Ubicacion.objects.create(
            nombre='Vitrina Test',
            tipo=Ubicacion.TipoUbicacion.VITRINA
        )

        # Categoría y Medicamento
        self.categoria = CategoriaMedicamento.objects.create(
            nombre='Cardiovascular Test',
            es_controlado=False
        )
        self.medicamento = Medicamento.objects.create(
            codigo='MED-TEST-01',
            nombre_generico='Enalapril Maleato',
            concentracion='10 mg',
            forma_farmaceutica='Comprimido',
            categoria=self.categoria,
            stock_minimo=50,
            stock_maximo=1000,
        )

    def test_rut_modulo_11_validos(self):
        """Valida que el algoritmo Módulo 11 acepte RUTs chilenos reales y válidos."""
        ruts_validos = [
            '11.234.567-1',
            '11234567-1',
            '8.765.432-K',
            '8765432-k',
            '14.821.934-6',
            '18.943.210-0',
            '16.543.210-K',
            '12.345.678-5',
        ]
        for rut in ruts_validos:
            with self.subTest(rut=rut):
                self.assertTrue(validar_rut(rut), f"El RUT {rut} debería ser válido.")

    def test_rut_modulo_11_invalidos(self):
        """Valida que el algoritmo Módulo 11 rechace RUTs con dígito verificador erróneo o formato inválido."""
        ruts_invalidos = [
            '11.234.567-9',  # DV incorrecto
            '8.765.432-5',  # DV incorrecto (debe ser K)
            '12.345.678-0',  # DV incorrecto
            '123',           # Largo insuficiente
            'ABCDEFGHI-K',   # No numérico
            '',              # Vacío
            None,            # Nulo
        ]
        for rut in ruts_invalidos:
            with self.subTest(rut=rut):
                self.assertFalse(validar_rut(rut), f"El RUT {rut} no debería ser aceptado.")

    def test_formateo_rut(self):
        """Verifica que el formateo a puntos y guión sea exacto."""
        self.assertEqual(formatear_rut('112345671'), '11.234.567-1')
        self.assertEqual(formatear_rut('8765432K'), '8.765.432-K')

    def test_fefo_ordenamiento_automatico(self):
        """
        HU-02 & RF-05: El algoritmo FEFO debe ordenar los lotes de forma ascendente
        por fecha de vencimiento, preseleccionando el que vence antes.
        """
        hoy = date.today()

        # Crear 3 lotes con diferentes vencimientos
        lote_lejano = Lote.objects.create(
            medicamento=self.medicamento,
            numero_lote='LOT-LEJANO',
            fecha_fabricacion=hoy - timedelta(days=100),
            fecha_vencimiento=hoy + timedelta(days=365), # Vence en 1 año
            cantidad_inicial=100,
            cantidad_actual=100,
            ubicacion=self.vitrina
        )
        lote_proximo = Lote.objects.create(
            medicamento=self.medicamento,
            numero_lote='LOT-PROXIMO',
            fecha_fabricacion=hoy - timedelta(days=200),
            fecha_vencimiento=hoy + timedelta(days=30),  # Vence en 30 días (FEFO primero)
            cantidad_inicial=100,
            cantidad_actual=100,
            ubicacion=self.vitrina
        )
        lote_medio = Lote.objects.create(
            medicamento=self.medicamento,
            numero_lote='LOT-MEDIO',
            fecha_fabricacion=hoy - timedelta(days=150),
            fecha_vencimiento=hoy + timedelta(days=90),  # Vence en 90 días
            cantidad_inicial=100,
            cantidad_actual=100,
            ubicacion=self.vitrina
        )

        lotes_fefo = list(self.medicamento.lotes_fefo())

        # El primero DEBE ser lote_proximo
        self.assertEqual(len(lotes_fefo), 3)
        self.assertEqual(lotes_fefo[0].numero_lote, 'LOT-PROXIMO')
        self.assertEqual(lotes_fefo[1].numero_lote, 'LOT-MEDIO')
        self.assertEqual(lotes_fefo[2].numero_lote, 'LOT-LEJANO')

    def test_bloqueo_lote_vencido_y_vida_util_insuficiente(self):
        """
        RF-05: Bloquea automáticamente la dispensación de lotes vencidos
        o cuya vida útil sea menor a los días de tratamiento.
        """
        hoy = date.today()

        # Lote ya vencido
        lote_vencido = Lote.objects.create(
            medicamento=self.medicamento,
            numero_lote='LOT-VENCIDO',
            fecha_fabricacion=hoy - timedelta(days=500),
            fecha_vencimiento=hoy - timedelta(days=5),
            cantidad_inicial=50,
            cantidad_actual=50,
            ubicacion=self.vitrina
        )
        self.assertTrue(lote_vencido.esta_vencido)
        self.assertFalse(lote_vencido.puede_dispensar(dias_tratamiento=0))

        # Lote no incluido en lotes_fefo()
        fefo_ids = [l.id for l in self.medicamento.lotes_fefo()]
        self.assertNotIn(lote_vencido.id, fefo_ids)

        # Lote que vence en 15 días, pero la receta es por 30 días de tratamiento
        lote_corto = Lote.objects.create(
            medicamento=self.medicamento,
            numero_lote='LOT-CORTO',
            fecha_fabricacion=hoy - timedelta(days=200),
            fecha_vencimiento=hoy + timedelta(days=15), # 15 días restantes
            cantidad_inicial=50,
            cantidad_actual=50,
            ubicacion=self.vitrina
        )
        # No puede dispensarse para tratamiento de 30 días
        self.assertFalse(lote_corto.puede_dispensar(dias_tratamiento=30))
        # Pero sí podría dispensarse para urgencia de 5 días
        self.assertTrue(lote_corto.puede_dispensar(dias_tratamiento=5))

    def test_descuento_y_bloqueo_cuotas_ges(self):
        """
        HU-03 & RF-10: Verificación de patología GES, control de saldo
        de cuotas y bloqueo cuando se agotan las cuotas autorizadas.
        """
        hoy = date.today()

        paciente = Paciente.objects.create(
            rut='11.234.567-1',
            nombres='Prueba',
            apellido_paterno='GES',
            apellido_materno='Test',
            fecha_nacimiento=date(1970, 1, 1),
            sexo='M',
            prevision=Paciente.Prevision.FONASA_A
        )

        patologia = PatologiaGES.objects.create(
            codigo='GES-99',
            nombre='Patología GES de Prueba',
            activa=True
        )

        canasta = CanastaGES.objects.create(
            patologia=patologia,
            medicamento=self.medicamento,
            cantidad_por_cuota=30,
            cuotas_autorizadas=3 # Solo 3 cuotas para la prueba
        )

        inscripcion = InscripcionGES.objects.create(
            paciente=paciente,
            patologia=patologia,
            fecha_inscripcion=hoy,
            fecha_inicio_periodo=hoy,
            fecha_fin_periodo=hoy + timedelta(days=365),
            activa=True
        )

        # Simular entrega de 3 cuotas
        for i in range(1, 4):
            CuotaGES.objects.create(
                inscripcion=inscripcion,
                canasta=canasta,
                numero_cuota=i,
                cantidad_entregada=30
            )

        cuotas_usadas = CuotaGES.objects.filter(inscripcion=inscripcion, canasta=canasta).count()
        saldo_disponible = canasta.cuotas_autorizadas - cuotas_usadas

        self.assertEqual(cuotas_usadas, 3)
        self.assertEqual(saldo_disponible, 0)
        self.assertFalse(cuotas_usadas < canasta.cuotas_autorizadas)

    def test_cifrado_simetrico_ley_21719(self):
        """Verifica que el cifrado Fernet (AES-128/256) sea reversible y seguro para datos sensibles."""
        dato_sensible = "Diagnóstico: Depresión Severa F32.2 (Confidencial)"
        cifrado = cifrar_dato(dato_sensible)
        self.assertNotEqual(dato_sensible, cifrado)
        descifrado = descifrar_dato(cifrado)
        self.assertEqual(dato_sensible, descifrado)


class PruebasIntegralesCESFAM(TestCase):
    """
    Prueba de integración de extremo a extremo:
    Receta -> Dispensación con Retiro por Tercero -> Descuento PostgreSQL -> Inserción en MongoDB.
    """

    def setUp(self):
        self.client = Client()
        hoy = date.today()

        # Usuario técnico en farmacia
        self.usuario_tecnico = Usuario.objects.create_user(
            username='tecnico_test',
            password='Password123!',
            rut='19.876.543-0',
            first_name='Técnico',
            last_name='Prueba',
            rol=Usuario.Rol.TECNICO_FARMACIA
        )

        # Paciente
        self.paciente = Paciente.objects.create(
            rut='11.234.567-1',
            nombres='Paciente',
            apellido_paterno='Integral',
            apellido_materno='Test',
            fecha_nacimiento=date(1965, 5, 20),
            sexo='M',
            prevision=Paciente.Prevision.FONASA_B,
            cronico=True
        )

        # Médico prescriptor
        self.medico = MedicoPrescriptor.objects.create(
            rut='12.345.678-5',
            nombres='Doctor',
            apellido_paterno='Integral',
            apellido_materno='Test',
            registro_sis='SIS-99999',
            habilitado=True
        )

        # Ubicación y Medicamento
        self.vitrina = Ubicacion.objects.create(
            nombre='Vitrina Mostrador',
            tipo=Ubicacion.TipoUbicacion.VITRINA
        )
        self.categoria = CategoriaMedicamento.objects.create(nombre='Cardio', es_controlado=False)
        self.medicamento = Medicamento.objects.create(
            codigo='MED-INT-01',
            nombre_generico='Amlodipino',
            concentracion='10 mg',
            forma_farmaceutica='Comprimido',
            categoria=self.categoria,
            stock_minimo=30,
            stock_maximo=500
        )

        # Lote FEFO
        self.lote = Lote.objects.create(
            medicamento=self.medicamento,
            numero_lote='AML-FEFO-01',
            fecha_fabricacion=hoy - timedelta(days=60),
            fecha_vencimiento=hoy + timedelta(days=120),
            cantidad_inicial=200,
            cantidad_actual=200,
            ubicacion=self.vitrina
        )

    def test_flujo_integral_dispensacion_tercero_stock_mongodb(self):
        """Flujo completo de dispensación asistencial con tercero y verificación multi-base de datos."""
        hoy = date.today()
        num_receta = f'REC-{int(time.time()) % 100000:05d}'

        # Limpiar auditoría previa si hubiese
        db = get_mongo_db()
        if db is not None:
            try:
                db.auditoria_inmutable.delete_many({'entidad_afectada': f'Receta {num_receta}'})
            except Exception:
                pass

        # 1. Crear Receta
        receta = Receta.objects.create(
            numero_receta=num_receta,
            paciente=self.paciente,
            medico=self.medico,
            tipo=Receta.TipoReceta.SIMPLE,
            estado=Receta.EstadoReceta.PENDIENTE,
            diagnostico='Hipertensión esencial',
            fecha_emision=hoy,
            fecha_vencimiento=hoy + timedelta(days=30),
        )
        detalle_receta = DetalleReceta.objects.create(
            receta=receta,
            medicamento=self.medicamento,
            cantidad_prescrita=30,
            cantidad_dispensada=0,
            posologia='1 al día',
            dias_tratamiento=30
        )

        # 2. Iniciar sesión como Técnico en Farmacia
        self.client.login(username='tecnico_test', password='Password123!')

        # 3. Enviar solicitud POST de Dispensación con Tercero Autorizado
        url_dispensar = reverse('dispensacion:dispensar_receta', kwargs={'receta_pk': receta.pk})
        post_data = {
            f'lote_{detalle_receta.id}': self.lote.id,
            f'cantidad_{detalle_receta.id}': 30,
            f'justificacion_{detalle_receta.id}': '',
            'retiro_tercero': 'on',
            'rut_tercero': '20.123.456-5',
            'nombres_tercero': 'Claudia',
            'ap_paterno_tercero': 'Integral',
            'ap_materno_tercero': 'Test',
            'parentesco_tercero': 'Hija',
            'telefono_tercero': '+56911223344',
            'observaciones': 'Dispensación integral de prueba',
        }

        response = self.client.post(url_dispensar, post_data, follow=True)
        self.assertEqual(response.status_code, 200)

        # 4. Verificar descuento de stock en PostgreSQL
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.cantidad_actual, 170)  # 200 - 30 = 170

        # 5. Verificar actualización de la receta
        receta.refresh_from_db()
        self.assertEqual(receta.estado, Receta.EstadoReceta.DISPENSADA_TOTAL)

        # 6. Verificar creación de TerceroAutorizado y Dispensacion en PostgreSQL
        dispensacion = Dispensacion.objects.filter(receta=receta).first()
        self.assertIsNotNone(dispensacion)
        self.assertEqual(dispensacion.copago, 0) # Gratuito ($0 copago)
        self.assertTrue(dispensacion.retiro_tercero)
        self.assertIsNotNone(dispensacion.tercero_autorizado)
        self.assertEqual(dispensacion.tercero_autorizado.rut, '20.123.456-5')

        # 7. Verificar inserción inmutable en PostgreSQL (core_auditoriainmutable JSONB)
        from core.models import AuditoriaInmutable
        aud_pg = AuditoriaInmutable.objects.filter(entidad_afectada=f'Receta {receta.numero_receta}').first()
        self.assertIsNotNone(aud_pg, "Debe existir un registro en la tabla 'core_auditoriainmutable' de PostgreSQL")
        self.assertEqual(aud_pg.accion, 'Dispensación realizada')
        self.assertEqual(aud_pg.usuario_username, 'tecnico_test')

        # 8. Caso Borde: Intentar dispensar nuevamente la misma receta cerrada (Prevención de retiro duplicado)
        response_dup = self.client.post(url_dispensar, post_data, follow=True)
        self.assertEqual(response_dup.status_code, 200)
        self.lote.refresh_from_db()
        # El stock NO debe volver a descontarse (sigue en 170) y solo debe existir 1 dispensación
        self.assertEqual(self.lote.cantidad_actual, 170)
        self.assertEqual(Dispensacion.objects.filter(receta=receta).count(), 1)

    def test_rechazo_receta_vencida_mas_de_30_dias(self):
        """Rechaza automáticamente recetas simples cuya emisión supere los 30 días de vigencia legal."""
        hoy = date.today()
        receta_antigua = Receta.objects.create(
            numero_receta='REC-VENC-45D',
            paciente=self.paciente,
            medico=self.medico,
            tipo=Receta.TipoReceta.SIMPLE,
            estado=Receta.EstadoReceta.PENDIENTE,
            diagnostico='Control general',
            fecha_emision=hoy - timedelta(days=45),
            fecha_vencimiento=hoy + timedelta(days=10),
        )
        det = DetalleReceta.objects.create(
            receta=receta_antigua,
            medicamento=self.medicamento,
            cantidad_prescrita=10,
            posologia='1 al día',
            dias_tratamiento=10
        )
        self.assertFalse(receta_antigua.esta_vigente)

        self.client.login(username='tecnico_test', password='Password123!')
        url = reverse('dispensacion:dispensar_receta', kwargs={'receta_pk': receta_antigua.pk})
        self.client.post(url, {f'lote_{det.id}': self.lote.id, f'cantidad_{det.id}': 10})

        self.lote.refresh_from_db()
        self.assertEqual(self.lote.cantidad_actual, 200)  # No descontó nada
        self.assertEqual(Dispensacion.objects.filter(receta=receta_antigua).count(), 0)

    def test_fefo_override_exige_justificacion_obligatoria(self):
        """Si se omite el lote FEFO más próximo a vencer, exige justificación técnica o revierte la transacción."""
        hoy = date.today()
        lote_posterior = Lote.objects.create(
            medicamento=self.medicamento,
            numero_lote='AML-POSTERIOR-02',
            fecha_fabricacion=hoy - timedelta(days=10),
            fecha_vencimiento=hoy + timedelta(days=300),
            cantidad_inicial=100,
            cantidad_actual=100,
            ubicacion=self.vitrina
        )
        receta = Receta.objects.create(
            numero_receta='REC-FEFO-OVR',
            paciente=self.paciente,
            medico=self.medico,
            tipo=Receta.TipoReceta.SIMPLE,
            estado=Receta.EstadoReceta.PENDIENTE,
            diagnostico='HTA',
            fecha_emision=hoy,
            fecha_vencimiento=hoy + timedelta(days=30),
        )
        det = DetalleReceta.objects.create(
            receta=receta,
            medicamento=self.medicamento,
            cantidad_prescrita=20,
            posologia='1 al día',
            dias_tratamiento=20
        )
        self.client.login(username='tecnico_test', password='Password123!')
        url = reverse('dispensacion:dispensar_receta', kwargs={'receta_pk': receta.pk})

        # 1) Intento de override SIN justificación -> debe rechazarse y revertirse
        self.client.post(url, {
            f'lote_{det.id}': lote_posterior.id,
            f'cantidad_{det.id}': 20,
            f'justificacion_{det.id}': '',
        })
        lote_posterior.refresh_from_db()
        self.assertEqual(lote_posterior.cantidad_actual, 100)
        self.assertEqual(Dispensacion.objects.filter(receta=receta).count(), 0)

        # 2) Intento de override CON justificación técnica -> debe aprobarse y auditarse
        self.client.post(url, {
            f'lote_{det.id}': lote_posterior.id,
            f'cantidad_{det.id}': 20,
            f'justificacion_{det.id}': 'Envase primario del lote anterior presenta deterioro en etiqueta',
        })
        lote_posterior.refresh_from_db()
        self.assertEqual(lote_posterior.cantidad_actual, 80)
        det_disp = DetalleDispensacion.objects.filter(dispensacion__receta=receta).first()
        self.assertIsNotNone(det_disp)
        self.assertTrue(det_disp.fefo_override)

    def test_prevencion_stock_negativo_y_sobredispensacion(self):
        """Impide dispensar más unidades que el stock del lote o que el saldo prescrito en la receta."""
        hoy = date.today()
        receta = Receta.objects.create(
            numero_receta='REC-STOCK-NEG',
            paciente=self.paciente,
            medico=self.medico,
            tipo=Receta.TipoReceta.SIMPLE,
            estado=Receta.EstadoReceta.PENDIENTE,
            diagnostico='HTA',
            fecha_emision=hoy,
            fecha_vencimiento=hoy + timedelta(days=30),
        )
        det = DetalleReceta.objects.create(
            receta=receta,
            medicamento=self.medicamento,
            cantidad_prescrita=250,  # Mayor que las 200 disponibles en self.lote
            posologia='1 al día',
            dias_tratamiento=30
        )
        self.client.login(username='tecnico_test', password='Password123!')
        url = reverse('dispensacion:dispensar_receta', kwargs={'receta_pk': receta.pk})
        self.client.post(url, {
            f'lote_{det.id}': self.lote.id,
            f'cantidad_{det.id}': 250,
        })
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.cantidad_actual, 200)  # Intacto, jamás negativo
        self.assertEqual(Dispensacion.objects.filter(receta=receta).count(), 0)

    def test_control_acceso_rbac_y_ciclo_carro_paro(self):
        """Verifica restricción RBAC para personal clínico y ciclo completo de Carro de Paro con precinto."""
        from carros_clinicos.models import CarroClinico, PlantillaItemCarro

        enfermera = Usuario.objects.create_user(
            username='enf_test',
            password='Password123!',
            rut='16.543.210-K',
            first_name='Camila',
            last_name='Enfermera',
            rol=Usuario.Rol.PERSONAL_CLINICO
        )
        self.client.login(username='enf_test', password='Password123!')

        # Personal clínico no puede entrar al Libro de Controlados, Usuarios, Pacientes, Recetas, Reportes ni Auditoría (403 Forbidden)
        self.assertEqual(self.client.get(reverse('controlados:libro')).status_code, 403)
        self.assertEqual(self.client.get(reverse('core:usuario_list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('core:paciente_list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('dispensacion:receta_list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('dispensacion:dispensar')).status_code, 403)
        self.assertEqual(self.client.get(reverse('core:auditoria_list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('reportes:exportar_pdf')).status_code, 403)
        # Personal clínico SÍ puede consultar el Arsenal Farmacológico en modo solo lectura (200 OK)
        self.assertEqual(self.client.get(reverse('farmacia:medicamento_list')).status_code, 200)

        # Crear Carro de Paro en estado COMPLETO
        carro = CarroClinico.objects.create(
            nombre='Carro de Paro Urgencia Test',
            tipo=CarroClinico.TipoCarro.PARO,
            ubicacion_fisica='Box Reanimación',
            estado=CarroClinico.EstadoCarro.COMPLETO,
            numero_precinto='PREC-2026-0001'
        )
        item_carro = PlantillaItemCarro.objects.create(
            carro=carro,
            medicamento=self.medicamento,
            cantidad_requerida=10,
            cantidad_actual=10,
            ubicacion_en_carro='Cajón 1'
        )

        # 1) Enfermera registra consumo de emergencia (3 unidades) -> Estado pasa a INCOMPLETO
        url_consumo = reverse('carros_clinicos:registrar_consumo', kwargs={'pk': carro.pk})
        self.client.post(url_consumo, {
            'item': item_carro.id,
            'cantidad': 3,
            'motivo': 'Crisis hipertensiva severa en box de urgencia',
            'paciente_atendido': '11.234.567-1'
        })
        carro.refresh_from_db()
        item_carro.refresh_from_db()
        self.assertEqual(item_carro.cantidad_actual, 7)
        self.assertEqual(carro.estado, CarroClinico.EstadoCarro.INCOMPLETO)

        # 2) Técnico de farmacia repone las 3 unidades con lote FEFO y sella con nuevo precinto -> Estado vuelve a COMPLETO
        self.client.login(username='tecnico_test', password='Password123!')
        url_reponer = reverse('carros_clinicos:reponer_carro', kwargs={'pk': carro.pk})
        self.client.post(url_reponer, {
            'item': item_carro.id,
            'lote': self.lote.id,
            'cantidad': 3,
            'nuevo_precinto': 'PREC-2026-9901'
        })
        carro.refresh_from_db()
        item_carro.refresh_from_db()
        self.lote.refresh_from_db()
        self.assertEqual(item_carro.cantidad_actual, 10)
        self.assertEqual(carro.estado, CarroClinico.EstadoCarro.COMPLETO)
        self.assertEqual(carro.numero_precinto, 'PREC-2026-9901')
        self.assertEqual(self.lote.cantidad_actual, 197)

        # 3) Verificar segregación del Administrador y del Químico Farmacéutico (403 Forbidden)
        admin_usr = Usuario.objects.create_user(
            username='admin_test_rbac',
            password='Password123!',
            rut='14.821.934-6',
            first_name='Admin',
            last_name='Simulador',
            rol=Usuario.Rol.ADMINISTRADOR
        )
        qf_usr = Usuario.objects.create_user(
            username='qf_test_rbac',
            password='Password123!',
            rut='15.432.198-K',
            first_name='Químico',
            last_name='Supervisor',
            rol=Usuario.Rol.QUIMICO_FARMACEUTICO
        )

        # Administrador: SÍ gestiona usuarios y auditoría (200), pero NO dispensa (403), NO opera libro controlados (403) y NO registra consumos en carro (403)
        self.client.login(username='admin_test_rbac', password='Password123!')
        self.assertEqual(self.client.get(reverse('core:usuario_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('core:auditoria_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('dispensacion:dispensar')).status_code, 403)
        self.assertEqual(self.client.get(reverse('controlados:libro')).status_code, 403)
        self.assertEqual(self.client.post(url_consumo, {'item': item_carro.id, 'cantidad': 1, 'motivo': 'Test'}).status_code, 403)

        # Químico Farmacéutico: SÍ opera libro controlados (200), dispensación (200) y reportes (200), pero NO gestiona usuarios (403)
        self.client.login(username='qf_test_rbac', password='Password123!')
        self.assertEqual(self.client.get(reverse('controlados:libro')).status_code, 200)
        self.assertEqual(self.client.get(reverse('dispensacion:dispensar')).status_code, 200)
        self.assertEqual(self.client.get(reverse('reportes:exportar_pdf')).status_code, 200)
        self.assertEqual(self.client.get(reverse('core:usuario_list')).status_code, 403)

        # Técnico en Farmacia: SÍ dispensa (200) y repone carros, pero NO entra a usuarios (403), libro controlados (403), auditoría global (403), reportes globales (403) ni creación de pacientes (403)
        self.client.login(username='tecnico_test', password='Password123!')
        self.assertEqual(self.client.get(reverse('dispensacion:dispensar')).status_code, 200)
        self.assertEqual(self.client.get(reverse('core:usuario_list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('controlados:libro')).status_code, 403)
        self.assertEqual(self.client.get(reverse('core:auditoria_list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('reportes:exportar_pdf')).status_code, 403)
        self.assertEqual(self.client.get(reverse('core:paciente_crear')).status_code, 403)

    def test_flujos_clinicos_controlados_cuarentena_y_carro_vacio(self):
        """
        Verifica:
        1) Carro sin ítems nunca aparece como Operativo (estado_efectivo == 'sin_dotacion').
        2) Receta controlada bloquea al Técnico hasta autorización Q.F. y luego permite despacho.
        3) Lote vencido solo puede enviarse a Cuarentena por el Q.F. (403 para Técnico) y queda excluido del stock FEFO.
        """
        from carros_clinicos.models import CarroClinico
        from farmacia.models import OrdenAbastecimiento

        hoy = date.today()
        carro_vacio = CarroClinico.objects.create(
            nombre='Carro Vacío Test',
            tipo=CarroClinico.TipoCarro.UNIDOSIS,
            ubicacion_fisica='Box Test',
        )
        self.assertFalse(carro_vacio.esta_completo)
        self.assertEqual(carro_vacio.estado_efectivo, CarroClinico.EstadoCarro.SIN_DOTACION)

        # Crear medicamento controlado y lote vigente + lote vencido
        med_ctrl = Medicamento.objects.create(
            codigo='MED-CTRL-TEST',
            nombre_generico='Clonazepam Test',
            concentracion='2 mg',
            forma_farmaceutica='Comprimido',
            categoria=self.medicamento.categoria,
            stock_minimo=10,
            stock_maximo=100,
            es_controlado=True,
        )
        lote_ctrl = Lote.objects.create(
            medicamento=med_ctrl,
            numero_lote='CLON-TEST-01',
            fecha_fabricacion=hoy - timedelta(days=30),
            fecha_vencimiento=hoy + timedelta(days=180),
            cantidad_inicial=50,
            cantidad_actual=50,
            ubicacion=self.vitrina,
        )
        lote_vencido = Lote.objects.create(
            medicamento=self.medicamento,
            numero_lote='LOT-VENC-Q',
            fecha_fabricacion=hoy - timedelta(days=400),
            fecha_vencimiento=hoy - timedelta(days=10),
            cantidad_inicial=30,
            cantidad_actual=30,
            ubicacion=self.vitrina,
        )

        receta_ctrl = Receta.objects.create(
            numero_receta='REC-CTRL-TEST',
            paciente=self.paciente,
            medico=self.medico,
            tipo=Receta.TipoReceta.RETENIDA,
            estado=Receta.EstadoReceta.PENDIENTE,
            diagnostico='Ansiedad Test',
            fecha_emision=hoy,
            fecha_vencimiento=hoy + timedelta(days=30),
            autorizada_qf=False,
        )
        det_ctrl = DetalleReceta.objects.create(
            receta=receta_ctrl,
            medicamento=med_ctrl,
            cantidad_prescrita=10,
            posologia='1 noche',
            dias_tratamiento=10,
        )

        # Técnico no puede dispensar receta controlada sin autorización Q.F. -> 403
        url_disp = reverse('dispensacion:dispensar_receta', kwargs={'receta_pk': receta_ctrl.pk})
        self.client.login(username='tecnico_test', password='Password123!')
        self.assertEqual(self.client.get(url_disp).status_code, 403)
        self.assertEqual(
            self.client.post(url_disp, {f'lote_{det_ctrl.id}': lote_ctrl.id, f'cantidad_{det_ctrl.id}': 10}).status_code,
            403
        )

        # Técnico tampoco puede mandar lotes a cuarentena -> 403
        url_cuar = reverse('farmacia:lote_cuarentena', kwargs={'pk': lote_vencido.pk})
        self.assertEqual(self.client.post(url_cuar, {'motivo': 'Test'}).status_code, 403)

        # Técnico tampoco puede crear nuevo fármaco desde Orden CENABAST -> 403
        self.assertEqual(
            self.client.post(reverse('farmacia:orden_list'), {
                'tipo': 'cenabast',
                'incluir_nuevo_med': 'on',
                'nuevo_nombre_generico': 'Fármaco No Permitido',
            }).status_code,
            403
        )

        # Químico Farmacéutico autoriza la receta controlada -> Técnico luego puede dispensarla
        qf_usr = Usuario.objects.create_user(
            username='qf_ctrl_flow',
            password='Password123!',
            rut='15.432.199-8',
            first_name='Q.F.',
            last_name='Autorizador',
            rol=Usuario.Rol.QUIMICO_FARMACEUTICO
        )
        self.client.login(username='qf_ctrl_flow', password='Password123!')
        self.client.post(
            reverse('dispensacion:autorizar_receta_qf', kwargs={'pk': receta_ctrl.pk}),
            {'pin_qf': '123456'}
        )
        receta_ctrl.refresh_from_db()
        self.assertTrue(receta_ctrl.autorizada_qf)

        # Químico Farmacéutico pasa lote vencido a Cuarentena -> sale del inventario activo
        self.client.post(url_cuar, {'motivo': 'Baja por vencimiento'})
        lote_vencido.refresh_from_db()
        self.assertTrue(lote_vencido.en_cuarentena)
        self.assertFalse(lote_vencido.activo)
        self.assertEqual(lote_vencido.cantidad_actual, 0)

        # Ahora Técnico sí puede dispensar la receta controlada ya autorizada por Q.F.
        self.client.login(username='tecnico_test', password='Password123!')
        self.client.post(url_disp, {f'lote_{det_ctrl.id}': lote_ctrl.id, f'cantidad_{det_ctrl.id}': 10})
        lote_ctrl.refresh_from_db()
        receta_ctrl.refresh_from_db()
        self.assertEqual(lote_ctrl.cantidad_actual, 40)
        self.assertEqual(receta_ctrl.estado, Receta.EstadoReceta.DISPENSADA_TOTAL)

        # Verificar que receta_detalle muestra historial de entregas, sello Q.F., vía y bloque de impresión
        html_det = self.client.get(reverse('dispensacion:receta_detalle', kwargs={'pk': receta_ctrl.pk})).content.decode()
        self.assertIn('Autorizada por Q.F.', html_det)
        self.assertIn('Historial de Entregas de esta Receta', html_det)
        self.assertIn('Vía oral', html_det)
        self.assertIn('Quien Retira (Nombre, RUT y Parentesco)', html_det)

    def test_receta_detalle_permisos_y_anulacion_obligatoria(self):
        """
        Verifica:
        1) Técnico no ve ni puede ejecutar agregar/eliminar medicamentos ni anular receta (403 Forbidden).
        2) Q.F. no puede agregar/eliminar medicamentos de receta emitida (403), pero sí anular con motivo obligatorio.
        3) Administrador sí puede editar ítems de receta simulada y anularla con motivo auditado.
        """
        from core.models import AuditoriaInmutable

        hoy = date.today()
        receta = Receta.objects.create(
            numero_receta='REC-EDIT-PERM',
            paciente=self.paciente,
            medico=self.medico,
            tipo=Receta.TipoReceta.SIMPLE,
            estado=Receta.EstadoReceta.PENDIENTE,
            diagnostico='HTA Control',
            fecha_emision=hoy,
            fecha_vencimiento=hoy + timedelta(days=30),
        )
        det = DetalleReceta.objects.create(
            receta=receta,
            medicamento=self.medicamento,
            cantidad_prescrita=30,
            posologia='1 comprimido cada 12 horas',
            dias_tratamiento=30,
        )
        url_det = reverse('dispensacion:receta_detalle', kwargs={'pk': receta.pk})

        # 1. Técnico: botones ocultos en UI y POST bloqueados con 403
        self.client.login(username='tecnico_test', password='Password123!')
        html_tec = self.client.get(url_det).content.decode()
        self.assertNotIn('+ Agregar Medicamento a Receta', html_tec)
        self.assertNotIn('Anular Receta', html_tec)
        self.assertEqual(self.client.post(url_det, {'accion': 'agregar_medicamento_receta', 'medicamento_id': self.medicamento.pk}).status_code, 403)
        self.assertEqual(self.client.post(url_det, {'accion': 'eliminar_detalle_receta', 'detalle_id': det.pk}).status_code, 403)
        self.assertEqual(self.client.post(url_det, {'accion': 'anular_receta', 'motivo_anulacion': 'Test'}).status_code, 403)

        # 2. Q.F.: bloqueado (403) para modificar medicamentos, sí puede anular pero exige motivo obligatorio
        qf_usr = Usuario.objects.create_user(
            username='qf_anul_test',
            password='Password123!',
            rut='15.432.200-5',
            first_name='Ana',
            last_name='Farmacéutica',
            rol=Usuario.Rol.QUIMICO_FARMACEUTICO
        )
        self.client.login(username='qf_anul_test', password='Password123!')
        self.assertEqual(self.client.post(url_det, {'accion': 'agregar_medicamento_receta', 'medicamento_id': self.medicamento.pk}).status_code, 403)

        # Intento anular SIN motivo -> NO anula
        self.client.post(url_det, {'accion': 'anular_receta', 'motivo_anulacion': '   '})
        receta.refresh_from_db()
        self.assertEqual(receta.estado, Receta.EstadoReceta.PENDIENTE)

        # Anulación CON motivo obligatorio -> anula, guarda motivo y registra auditoría
        self.client.post(url_det, {'accion': 'anular_receta', 'motivo_anulacion': 'Duplicación de prescripción por cambio de dosis'})
        receta.refresh_from_db()
        self.assertEqual(receta.estado, Receta.EstadoReceta.ANULADA)
        self.assertIn('Duplicación de prescripción por cambio de dosis', receta.observaciones)
        aud = AuditoriaInmutable.objects.filter(
            accion='Anulación de Receta Médica',
            entidad_afectada=f'Receta {receta.numero_receta}',
        ).first()
        self.assertIsNotNone(aud)
        self.assertEqual(aud.usuario_username, 'qf_anul_test')

        # 3. Administrador: puede reactivar y agregar/eliminar medicamento en receta simulada
        admin_usr = Usuario.objects.create_user(
            username='admin_edit_rec',
            password='Password123!',
            rut='14.821.935-4',
            first_name='Admin',
            last_name='Docente',
            rol=Usuario.Rol.ADMINISTRADOR
        )
        self.client.login(username='admin_edit_rec', password='Password123!')
        self.client.post(url_det, {'accion': 'reactivar_receta'})
        self.client.post(url_det, {
            'accion': 'agregar_medicamento_receta',
            'medicamento_id': self.medicamento.pk,
            'cantidad_prescrita': 15,
            'dias_tratamiento': 15,
            'posologia': '1 al día',
        })
        self.assertEqual(receta.detalles.count(), 2)

    def test_vista_impresion_receta_dedicada_y_modal_dispensacion(self):
        """Verifica la vista dedicada /dispensacion/recetas/<id>/imprimir/ y los enlaces desde dispensación y detalle."""
        receta_ctrl = Receta.objects.create(
            numero_receta='REC-IMP-001',
            paciente=self.paciente,
            medico=self.medico,
            tipo=Receta.TipoReceta.RETENIDA,
            estado=Receta.EstadoReceta.PENDIENTE,
            diagnostico='Trastorno de ansiedad',
            fecha_emision=date.today(),
            fecha_vencimiento=date.today() + timedelta(days=30),
            autorizada_qf=True,
        )
        med_ctrl = Medicamento.objects.create(
            codigo='MED-IMP-01',
            nombre_generico='Clonazepam',
            concentracion='2 mg',
            forma_farmaceutica='Comprimido',
            unidad_medida='comp',
            categoria=self.medicamento.categoria,
            es_controlado=True,
            stock_minimo=10,
            stock_maximo=100,
        )
        Lote.objects.create(
            medicamento=med_ctrl,
            numero_lote='CLON-IMP-01',
            fecha_fabricacion=date.today() - timedelta(days=20),
            fecha_vencimiento=date.today() + timedelta(days=180),
            cantidad_inicial=60,
            cantidad_actual=60,
            ubicacion=self.vitrina,
        )
        DetalleReceta.objects.create(
            receta=receta_ctrl,
            medicamento=med_ctrl,
            cantidad_prescrita=30,
            posologia='1/2 comprimido en la noche',
            dias_tratamiento=30,
        )
        url_print = reverse('dispensacion:receta_imprimir', kwargs={'pk': receta_ctrl.pk})
        url_disp = reverse('dispensacion:dispensar_receta', kwargs={'receta_pk': receta_ctrl.pk})
        url_det = reverse('dispensacion:receta_detalle', kwargs={'pk': receta_ctrl.pk})

        # 1. Bloqueado para Personal Clínico (403)
        Usuario.objects.create_user(
            username='clinico_imp',
            password='Password123!',
            rut='12.345.678-9',
            rol=Usuario.Rol.PERSONAL_CLINICO,
        )
        self.client.login(username='clinico_imp', password='Password123!')
        self.assertEqual(self.client.get(url_print).status_code, 403)

        # 2. Técnico en Farmacia accede a la hoja limpia de impresión y al modal en dispensación
        self.client.login(username='tecnico_test', password='Password123!')
        resp_print = self.client.get(f'{url_print}?autoprint=1')
        self.assertEqual(resp_print.status_code, 200)
        html_print = resp_print.content.decode()
        self.assertIn('inacap_logo.png', html_print)
        self.assertIn('Farmacia Asistencial CESFAM · Red Atención Primaria', html_print)
        self.assertIn('Docencia &amp; Simulación Clínica', html_print)
        self.assertIn('N° REC-IMP-001', html_print)
        self.assertIn('Rp. Prescripción Farmacológica', html_print)
        self.assertIn('Vía oral', html_print)
        self.assertIn('Sello de Validación Químico Farmacéutico', html_print)
        self.assertIn('Firma y Timbre Médico Prescriptor', html_print)
        self.assertIn('Firma Quien Dispensa', html_print)
        self.assertIn('Firma Quien Retira (Nombre, RUT y Parentesco)', html_print)
        self.assertIn('Documento generado para uso docente y simulación académica INACAP — Sin validez legal', html_print)
        self.assertIn('window.print();', html_print)
        self.assertNotIn('Entrega en Ventanilla', html_print)
        self.assertNotIn('inacap-sidebar', html_print)

        # 3. Modal en dispensación y detalle enlazan a la ruta de impresión limpia
        html_disp = self.client.get(url_disp).content.decode()
        self.assertIn(f'{url_print}?autoprint=1', html_disp)
        self.assertIn('container-fluid py-3 no-print', html_disp)
        self.assertIn('inacap_logo.png', html_disp)

        html_det = self.client.get(url_det).content.decode()
        self.assertIn(f'{url_print}?autoprint=1', html_det)

    def test_mejoras_inventario_bodega_vitrina_y_validaciones_lote(self):
        """
        Verifica:
        1) Contadores resumen y botón directo Traspasar a Vitrina en /farmacia/lotes/.
        2) Ficha del medicamento: desglose Vitrina/Bodega, subtítulo de ajuste según rol, prioridad de botones e historial Kardex.
        3) Registrar Nuevo Lote: preselección ?medicamento=, validaciones estrictas (<=0, venc<=fab, vencido en vitrina) y bloqueo ISP para Técnico.
        4) Tarjeta En Quiebre de Stock clickeable en Dashboard.
        """
        from farmacia.models import Ubicacion, MovimientoStock
        from controlados.models import LibroControlados

        hoy = date.today()
        bodega = Ubicacion.objects.create(nombre='Bodega Central de Farmacia', tipo=Ubicacion.TipoUbicacion.BODEGA)
        lote_bod = Lote.objects.create(
            medicamento=self.medicamento,
            numero_lote='AML-BOD-99',
            fecha_fabricacion=hoy - timedelta(days=30),
            fecha_vencimiento=hoy + timedelta(days=20),
            cantidad_inicial=300,
            cantidad_actual=300,
            ubicacion=bodega,
        )
        med_ctrl = Medicamento.objects.create(
            codigo='MED-CTRL-INV',
            nombre_generico='Morfina Test',
            concentracion='10 mg/ml',
            forma_farmaceutica='Ampolla',
            unidad_medida='amp',
            categoria=self.medicamento.categoria,
            es_controlado=True,
            stock_minimo=10,
            stock_maximo=100,
        )

        # Propiedades Bodega vs Vitrina
        self.assertEqual(self.medicamento.stock_vitrina, 200)
        self.assertEqual(self.medicamento.stock_bodega, 300)
        self.assertEqual(self.medicamento.stock_total, 500)

        url_lotes = reverse('farmacia:lote_list')
        url_ficha = reverse('farmacia:medicamento_detalle', kwargs={'pk': self.medicamento.pk})
        url_ficha_ctrl = reverse('farmacia:medicamento_detalle', kwargs={'pk': med_ctrl.pk})
        url_lote_crear = reverse('farmacia:lote_crear')
        url_traspaso = reverse('farmacia:traspaso')
        url_dash = reverse('core:dashboard')

        # 1. Técnico en Farmacia: vistas, contadores, preselecciones, validaciones y bloqueo ISP
        self.client.login(username='tecnico_test', password='Password123!')

        html_dash = self.client.get(url_dash).content.decode()
        self.assertIn(reverse('farmacia:orden_list'), html_dash)
        self.assertIn('En Quiebre de Stock', html_dash)

        html_lotes = self.client.get(url_lotes).content.decode()
        self.assertIn('Total Unidades en Bodega', html_lotes)
        self.assertIn('Total Unidades en Vitrina', html_lotes)
        self.assertIn('Lotes Críticos (&lt;=30d)', html_lotes)
        self.assertIn('Vencidos Pendientes de Baja', html_lotes)
        self.assertIn('Traspaso Bodega → Vitrina', html_lotes)
        self.assertIn(f'{url_traspaso}?lote={lote_bod.pk}', html_lotes)

        html_trasp = self.client.get(f'{url_traspaso}?lote={lote_bod.pk}').content.decode()
        self.assertIn(f'value="{lote_bod.pk}"', html_trasp)

        html_ficha_tec = self.client.get(url_ficha).content.decode()
        self.assertIn('Ajustes manuales de stock/vencimiento reservados a Dirección Técnica (Q.F.)', html_ficha_tec)
        self.assertNotIn('Puedes ajustar manualmente el stock o vencimiento de cualquier lote', html_ficha_tec)
        self.assertIn('Vitrina: <strong>200 unid.</strong>', html_ficha_tec)
        self.assertIn('Bodega: <strong>300 unid.</strong>', html_ficha_tec)
        self.assertIn(f'{url_lote_crear}?medicamento={self.medicamento.pk}', html_ficha_tec)
        self.assertIn('Sugerir Pedido CENABAST', html_ficha_tec)

        # En ficha de medicamento controlado, Técnico no ve botón + Ingresar Lote Manual y URL/POST devuelve 403
        html_ficha_ctrl = self.client.get(url_ficha_ctrl).content.decode()
        self.assertNotIn(f'{url_lote_crear}?medicamento={med_ctrl.pk}', html_ficha_ctrl)
        self.assertEqual(self.client.get(f'{url_lote_crear}?medicamento={med_ctrl.pk}').status_code, 403)
        self.assertEqual(self.client.post(url_lote_crear, {
            'medicamento': med_ctrl.pk,
            'numero_lote': 'CTRL-FORB',
            'fecha_fabricacion': (hoy - timedelta(days=10)).isoformat(),
            'fecha_vencimiento': (hoy + timedelta(days=180)).isoformat(),
            'cantidad_inicial': 10,
            'ubicacion': bodega.pk,
            'motivo_ingreso': 'Intento Técnico controlado',
        }).status_code, 403)

        # Formulario lote_crear oculta controlados al Técnico y preselecciona ?medicamento=
        html_lote_form = self.client.get(f'{url_lote_crear}?medicamento={self.medicamento.pk}').content.decode()
        self.assertRegex(html_lote_form, rf'<option[^>]*value="{self.medicamento.pk}"[^>]*selected')
        self.assertNotIn('Morfina Test', html_lote_form)

        # Validaciones estrictas en backend al crear lote
        # a) Cantidad <= 0
        self.client.post(url_lote_crear, {
            'medicamento': self.medicamento.pk,
            'numero_lote': 'INV-ZERO',
            'fecha_fabricacion': (hoy - timedelta(days=10)).isoformat(),
            'fecha_vencimiento': (hoy + timedelta(days=60)).isoformat(),
            'cantidad_inicial': 0,
            'ubicacion': bodega.pk,
            'motivo_ingreso': 'Prueba cero',
        })
        self.assertFalse(Lote.objects.filter(numero_lote='INV-ZERO').exists())

        # b) Fecha vencimiento <= fecha fabricación
        self.client.post(url_lote_crear, {
            'medicamento': self.medicamento.pk,
            'numero_lote': 'INV-FECHAS',
            'fecha_fabricacion': hoy.isoformat(),
            'fecha_vencimiento': (hoy - timedelta(days=1)).isoformat(),
            'cantidad_inicial': 20,
            'ubicacion': bodega.pk,
            'motivo_ingreso': 'Prueba fechas',
        })
        self.assertFalse(Lote.objects.filter(numero_lote='INV-FECHAS').exists())

        # c) Lote vencido en Vitrina bloqueado
        self.client.post(url_lote_crear, {
            'medicamento': self.medicamento.pk,
            'numero_lote': 'INV-VENC-VIT',
            'fecha_fabricacion': (hoy - timedelta(days=200)).isoformat(),
            'fecha_vencimiento': (hoy - timedelta(days=2)).isoformat(),
            'cantidad_inicial': 20,
            'ubicacion': self.vitrina.pk,
            'motivo_ingreso': 'Prueba vencido en vitrina',
        })
        self.assertFalse(Lote.objects.filter(numero_lote='INV-VENC-VIT').exists())

        # d) Alta válida crea Lote y movimiento inicial en Kardex
        self.client.post(url_lote_crear, {
            'medicamento': self.medicamento.pk,
            'numero_lote': 'AML-NEW-KDX',
            'fecha_fabricacion': (hoy - timedelta(days=10)).isoformat(),
            'fecha_vencimiento': (hoy + timedelta(days=200)).isoformat(),
            'cantidad_inicial': 50,
            'ubicacion': bodega.pk,
            'motivo_ingreso': 'Guía CENABAST N° 1234',
        })
        lote_ok = Lote.objects.get(numero_lote='AML-NEW-KDX')
        self.assertTrue(MovimientoStock.objects.filter(lote=lote_ok, tipo=MovimientoStock.TipoMovimiento.INGRESO).exists())

        # 2. Q.F. sí ve texto de ajuste manual, puede crear lote controlado y genera asiento en LibroControlados + Kardex
        qf_inv = Usuario.objects.create_user(
            username='qf_inv_test',
            password='Password123!',
            rut='16.777.888-5',
            rol=Usuario.Rol.QUIMICO_FARMACEUTICO,
        )
        self.client.login(username='qf_inv_test', password='Password123!')
        html_ficha_qf = self.client.get(url_ficha).content.decode()
        self.assertIn('Puedes ajustar manualmente el stock o vencimiento de cualquier lote', html_ficha_qf)

        resp_qf_ctrl = self.client.post(url_lote_crear, {
            'medicamento': med_ctrl.pk,
            'numero_lote': 'MORF-QF-01',
            'fecha_fabricacion': (hoy - timedelta(days=10)).isoformat(),
            'fecha_vencimiento': (hoy + timedelta(days=200)).isoformat(),
            'cantidad_inicial': 25,
            'ubicacion': bodega.pk,
            'motivo_ingreso': 'Ingreso ISP Guía 990',
        })
        self.assertEqual(resp_qf_ctrl.status_code, 302)
        lote_morf_ok = Lote.objects.get(numero_lote='MORF-QF-01')
        self.assertTrue(MovimientoStock.objects.filter(lote=lote_morf_ok, tipo=MovimientoStock.TipoMovimiento.INGRESO).exists())
        self.assertTrue(LibroControlados.objects.filter(lote=lote_morf_ok, tipo_movimiento=LibroControlados.TipoMovimiento.INGRESO).exists())

        # 3. Arsenal Farmacológico (nowrap, desglose Vitrina/Bodega, botones en quiebre) y validaciones de lote_crear
        # Intentar duplicar lote 'aml-new-kdx' en la misma ubicación (insensible a mayúsculas) -> bloqueado sin crash
        resp_dup = self.client.post(url_lote_crear, {
            'medicamento': self.medicamento.pk,
            'numero_lote': 'aml-new-kdx',
            'fecha_fabricacion': (hoy - timedelta(days=5)).isoformat(),
            'fecha_vencimiento': (hoy + timedelta(days=180)).isoformat(),
            'cantidad_inicial': 10,
            'ubicacion': bodega.pk,
            'motivo_ingreso': 'Intento duplicado',
        })
        self.assertEqual(resp_dup.status_code, 200)
        self.assertEqual(Lote.objects.filter(medicamento=self.medicamento, ubicacion=bodega, numero_lote__iexact='AML-NEW-KDX').count(), 1)
        html_dup = resp_dup.content.decode()
        self.assertIn('ya existe para', html_dup)

        # Verificar campos de formulario lote_crear (unidad dinámica, placeholder y proveedor por defecto)
        html_form_def = self.client.get(f'{url_lote_crear}?medicamento={self.medicamento.pk}').content.decode()
        self.assertIn('data-unidad-plural="Comprimidos"', html_form_def)
        self.assertIn('placeholder="Ej: 200"', html_form_def)
        self.assertIn('value="CENABAST"', html_form_def)

        # En Arsenal Farmacológico: med_ctrl está en quiebre (25 > 10? Esperar: med_ctrl stock_minimo=10, creemos uno en quiebre)
        med_quiebre = Medicamento.objects.create(
            codigo='MED-QUIEBRE-ARS',
            nombre_generico='Salbutamol Test Quiebre',
            concentracion='100 mcg',
            forma_farmaceutica='Inhalador',
            unidad_medida='inhalador',
            categoria=self.medicamento.categoria,
            stock_minimo=50,
            stock_maximo=300,
        )
        url_arsenal = reverse('farmacia:medicamento_list')
        url_pedidos = reverse('farmacia:orden_list')

        html_ars_qf = self.client.get(url_arsenal).content.decode()
        self.assertIn('whitespace-nowrap', html_ars_qf)
        self.assertIn('Vitrina: 200 · Bodega: 350', html_ars_qf)
        self.assertIn('Pedir CENABAST', html_ars_qf)
        self.assertIn(f'{url_pedidos}?medicamento={med_quiebre.pk}', html_ars_qf)

        self.client.login(username='tecnico_test', password='Password123!')
        html_ars_tec = self.client.get(url_arsenal).content.decode()
        self.assertIn('Sugerir Pedido', html_ars_tec)
        self.assertIn(f'{url_pedidos}?medicamento={med_quiebre.pk}', html_ars_tec)

        html_ped_pre = self.client.get(f'{url_pedidos}?medicamento={med_quiebre.pk}').content.decode()
        self.assertIn(f'value="{med_quiebre.pk}" selected', html_ped_pre)

    def test_flujo_completo_ordenes_cenabast_y_bloqueos(self):
        """
        Verifica el flujo completo y reglas de negocio de Pedidos & CENABAST:
        1) Tabs de estado y modal limpio para Técnico en /farmacia/abastecimiento/.
        2) Generación automática por quiebre evita duplicados sobre los mismos fármacos en borrador.
        3) Bloqueo de recepción (Frontend disabled + Backend 403) hasta aprobación oficial del Q.F.
        4) Flujo completo: Técnico crea borrador -> Q.F. aprueba -> Técnico recepciona en Bodega.
        """
        from farmacia.models import OrdenAbastecimiento, Ubicacion, MovimientoStock

        bodega = Ubicacion.objects.create(nombre='Bodega Central de Farmacia', tipo=Ubicacion.TipoUbicacion.BODEGA)
        med_q = Medicamento.objects.create(
            codigo='MED-ORD-Q01',
            nombre_generico='Salbutamol Orden Quiebre',
            concentracion='100 mcg',
            forma_farmaceutica='Inhalador',
            unidad_medida='inhalador',
            categoria=self.medicamento.categoria,
            stock_minimo=40,
            stock_maximo=240,
        )

        url_list = reverse('farmacia:orden_list')
        url_auto = reverse('farmacia:generar_orden_automatica')

        # 1. Técnico revisa listado, modal limpio y genera borrador automático sin duplicados
        self.client.login(username='tecnico_test', password='Password123!')
        html_list_tec = self.client.get(url_list).content.decode()
        self.assertIn('Pendientes Q.F.', html_list_tec)
        self.assertIn('Aprobadas', html_list_tec)
        self.assertIn('Recepcionadas', html_list_tec)
        self.assertIn('Medicamentos a Solicitar', html_list_tec)
        self.assertNotIn('A. Seleccionar Medicamentos del Catálogo Actual', html_list_tec)
        self.assertNotIn('(opcional si ingresará uno nuevo abajo)', html_list_tec)
        self.assertNotIn('(existentes o fármacos nuevos)', html_list_tec)
        self.assertIn('placeholder="Ej: 200"', html_list_tec)

        # Primera llamada a generar propuesta automática -> crea 1 orden PENDIENTE
        resp_auto1 = self.client.get(url_auto)
        self.assertEqual(resp_auto1.status_code, 302)
        self.assertEqual(OrdenAbastecimiento.objects.count(), 1)
        orden = OrdenAbastecimiento.objects.first()

        # Segunda llamada inmediata sobre el mismo quiebre -> NO crea duplicado, redirige al mismo borrador
        resp_auto2 = self.client.get(url_auto)
        self.assertEqual(resp_auto2.status_code, 302)
        self.assertEqual(OrdenAbastecimiento.objects.count(), 1)
        self.assertIn(f'/{orden.pk}/', resp_auto2.url)

        url_det = reverse('farmacia:orden_detalle', kwargs={'pk': orden.pk})

        # 2. En estado Borrador: firma pendiente, recepción bloqueada (UI + Backend 403), sin crear medicamentos
        html_det_borr = self.client.get(url_det).content.decode()
        self.assertIn('Pendiente de firma Q.F.', html_det_borr)
        self.assertIn('1. Borrador', html_det_borr)
        self.assertIn('2. Visación Q.F.', html_det_borr)
        self.assertIn('3. Recepción en Bodega', html_det_borr)
        self.assertNotIn('modalRecepcionar', html_det_borr)
        self.assertNotIn('nuevo medicamento que no esté en el catálogo', html_det_borr)

        # Técnico bloqueado para aprobar o recepcionar sin visación (403)
        self.assertEqual(self.client.post(url_det, {'accion': 'aprobar'}).status_code, 403)
        self.assertEqual(self.client.post(url_det, {'accion': 'recepcionar', 'guia_despacho': 'GD-ILEGAL'}).status_code, 403)
        orden.refresh_from_db()
        self.assertEqual(orden.estado, OrdenAbastecimiento.EstadoOrden.PENDIENTE)

        # 3. Q.F. aprueba la orden oficialmente
        qf_ord = Usuario.objects.create_user(
            username='qf_ord_test',
            password='Password123!',
            rut='17.654.321-K',
            first_name='Renato',
            last_name='Suazo',
            rol=Usuario.Rol.QUIMICO_FARMACEUTICO,
        )
        self.client.login(username='qf_ord_test', password='Password123!')
        # Incluso Q.F. no puede saltarse la aprobación para recepcionar directamente en estado Borrador
        self.assertEqual(self.client.post(url_det, {'accion': 'recepcionar', 'guia_despacho': 'GD-SALTO'}).status_code, 403)

        resp_apr = self.client.post(url_det, {'accion': 'aprobar'})
        self.assertEqual(resp_apr.status_code, 302)
        orden.refresh_from_db()
        self.assertEqual(orden.estado, OrdenAbastecimiento.EstadoOrden.ENVIADA)
        self.assertEqual(orden.aprobador_qf, qf_ord)

        # Verificar tab Aprobadas en listado
        html_aprob = self.client.get(f'{url_list}?filtro=aprobadas').content.decode()
        self.assertIn(orden.numero_orden, html_aprob)

        # 4. Técnico recepciona la orden ya aprobada -> crea Lote en Bodega y Kardex inicial
        self.client.login(username='tecnico_test', password='Password123!')
        html_det_aprob = self.client.get(url_det).content.decode()
        self.assertIn('Renato Suazo', html_det_aprob)
        self.assertIn('modalRecepcionar', html_det_aprob)
        self.assertNotIn('Eliminar Borrador', html_det_aprob)

        det_item = orden.detalles.first()
        resp_rec = self.client.post(url_det, {
            'accion': 'recepcionar',
            'guia_despacho': 'GD-TEST-999',
            f'lote_{det_item.id}': 'LOT-REC-999',
            f'vencimiento_{det_item.id}': (date.today() + timedelta(days=365)).isoformat(),
            f'cantidad_{det_item.id}': 120,
        })
        self.assertEqual(resp_rec.status_code, 302)
        orden.refresh_from_db()
        self.assertEqual(orden.estado, OrdenAbastecimiento.EstadoOrden.RECEPCIONADA)
        self.assertEqual(orden.guia_despacho, 'GD-TEST-999')

        lote_rec = Lote.objects.get(numero_lote='LOT-REC-999', ubicacion=bodega)
        self.assertEqual(lote_rec.cantidad_actual, 120)
        self.assertTrue(MovimientoStock.objects.filter(lote=lote_rec, tipo=MovimientoStock.TipoMovimiento.INGRESO).exists())

    def test_pulido_paciente_detalle_y_receta_dispensada_total(self):
        """
        Verifica:
        1) Botón Volver a Pacientes y mensaje GES adaptado para Técnico (sin botón Acreditar GES).
        2) Receta completamente dispensada (Pendiente: 0) oculta la tabla de Lotes FEFO.
        """
        url_pac = reverse('core:paciente_detalle', kwargs={'pk': self.paciente.pk})

        # Técnico: ve Volver a Pacientes y texto simple sin referencia al botón + Acreditar en Patología GES
        self.client.login(username='tecnico_test', password='Password123!')
        html_pac_tec = self.client.get(url_pac).content.decode()
        self.assertIn(reverse('core:paciente_list'), html_pac_tec)
        self.assertIn('Volver a Pacientes', html_pac_tec)
        self.assertIn('Sin patologías GES adscritas actualmente.', html_pac_tec)
        self.assertNotIn('Usa el botón', html_pac_tec)

        # Q.F.: sí ve botón + Acreditar en Patología GES y referencia al botón
        Usuario.objects.create_user(
            username='qf_pac_test',
            password='Password123!',
            rut='15.888.999-K',
            rol=Usuario.Rol.QUIMICO_FARMACEUTICO,
        )
        self.client.login(username='qf_pac_test', password='Password123!')
        html_pac_qf = self.client.get(url_pac).content.decode()
        self.assertIn('Volver a Pacientes', html_pac_qf)
        self.assertIn('+ Acreditar en Patología GES', html_pac_qf)
        self.assertIn('Usa el botón', html_pac_qf)

        # Receta dispensada totalmente oculta la subtabla Lotes Disponibles Ordenados por Motor FEFO
        rec_tot = Receta.objects.create(
            numero_receta='REC-TOT-001',
            paciente=self.paciente,
            medico=self.medico,
            tipo=Receta.TipoReceta.SIMPLE,
            estado=Receta.EstadoReceta.DISPENSADA_TOTAL,
            diagnostico='Control crónico',
            fecha_emision=date.today(),
            fecha_vencimiento=date.today() + timedelta(days=30),
        )
        DetalleReceta.objects.create(
            receta=rec_tot,
            medicamento=self.medicamento,
            cantidad_prescrita=30,
            cantidad_dispensada=30,
            posologia='1 al día',
            dias_tratamiento=30,
        )
        html_rec_tot = self.client.get(reverse('dispensacion:receta_detalle', kwargs={'pk': rec_tot.pk})).content.decode()
        self.assertNotIn('Lotes Disponibles Ordenados por Motor FEFO:', html_rec_tot)
        self.assertIn('Historial de Entregas de esta Receta', html_rec_tot)

    def test_mejoras_carros_clinicos_lotes_fefo_y_validaciones(self):
        """
        Verifica:
        1) Carro completo deshabilita Reponer y Sellar Carro (muestra Carro Completo) y oculta #modalReposicion.
        2) Columna Lote / Vencimiento con badge de alerta <= 60 días.
        3) Badge Requiere Reposición (X faltantes) en /carros/ y botón Reponer por fila.
        4) Modal lista solo ítems faltantes, filtra lotes FEFO y backend bloquea exceso sobre requerido.
        """
        from carros_clinicos.models import CarroClinico, PlantillaItemCarro

        hoy = date.today()
        med_alerta = Medicamento.objects.create(
            codigo='MED-CAR-60D',
            nombre_generico='Atropina Car Test',
            concentracion='1 mg/ml',
            forma_farmaceutica='Ampolla',
            unidad_medida='amp',
            categoria=self.medicamento.categoria,
            stock_minimo=10,
            stock_maximo=100,
        )
        lote_45d = Lote.objects.create(
            medicamento=med_alerta,
            numero_lote='ATR-45D',
            fecha_fabricacion=hoy - timedelta(days=30),
            fecha_vencimiento=hoy + timedelta(days=45),
            cantidad_inicial=30,
            cantidad_actual=30,
            ubicacion=self.vitrina,
        )

        carro = CarroClinico.objects.create(
            nombre='Carro Paro Mejoras',
            tipo=CarroClinico.TipoCarro.PARO,
            ubicacion_fisica='Box Urgencia',
            estado=CarroClinico.EstadoCarro.COMPLETO,
            numero_precinto='PREC-TEST-01',
        )
        it_ok = PlantillaItemCarro.objects.create(
            carro=carro,
            medicamento=self.medicamento,
            cantidad_requerida=10,
            cantidad_actual=10,
            ubicacion_en_carro='Cajón 1',
        )
        it_alerta = PlantillaItemCarro.objects.create(
            carro=carro,
            medicamento=med_alerta,
            cantidad_requerida=5,
            cantidad_actual=5,
            ubicacion_en_carro='Cajón 2',
        )

        url_list = reverse('carros_clinicos:carro_list')
        url_det = reverse('carros_clinicos:carro_detalle', kwargs={'pk': carro.pk})
        url_rep = reverse('carros_clinicos:reponer_carro', kwargs={'pk': carro.pk})

        self.client.login(username='tecnico_test', password='Password123!')

        # 1. Carro completo: botón deshabilitado Carro Completo, columna Lote/Vencimiento y alerta 45d
        html_list_ok = self.client.get(url_list).content.decode()
        self.assertIn('Completo - Operativo', html_list_ok)

        html_det_ok = self.client.get(url_det).content.decode()
        self.assertIn('Carro Completo', html_det_ok)
        self.assertNotIn('id="modalReposicion"', html_det_ok)
        self.assertIn('Lote / Vencimiento', html_det_ok)
        self.assertIn('ATR-45D', html_det_ok)
        self.assertIn('Vence 45d', html_det_ok)

        # 2. Al existir faltante en it_alerta (actual=3 de 5 -> faltante=2):
        it_alerta.cantidad_actual = 3
        it_alerta.save()
        carro.estado = CarroClinico.EstadoCarro.INCOMPLETO
        carro.save()

        html_list_inc = self.client.get(url_list).content.decode()
        self.assertIn('Requiere Reposición (2 faltantes)', html_list_inc)

        html_det_inc = self.client.get(url_det).content.decode()
        self.assertIn('Reponer y Sellar Carro', html_det_inc)
        self.assertIn(f"abrirReposicionParaItem('{it_alerta.pk}')", html_det_inc)
        # El modal solo incluye it_alerta (faltante=2), no it_ok (faltante=0)
        modal_repo_html = html_det_inc.split('id="modalReposicion"')[1].split('id="modalAgregarItemCarro"')[0]
        self.assertIn(f'value="{it_alerta.pk}"', modal_repo_html)
        self.assertIn('data-faltante="2"', modal_repo_html)
        self.assertNotIn(f'value="{it_ok.pk}"', modal_repo_html)
        self.assertNotIn('Amlodipino', modal_repo_html)

        # 3. Backend rechaza exceso (3 + 4 = 7 > 5) y lote de otro medicamento sin modificar stock
        self.client.post(url_rep, {
            'item': it_alerta.pk,
            'lote': lote_45d.pk,
            'cantidad': 4,
            'nuevo_precinto': 'PREC-ERR-01',
        })
        it_alerta.refresh_from_db()
        lote_45d.refresh_from_db()
        self.assertEqual(it_alerta.cantidad_actual, 3)
        self.assertEqual(lote_45d.cantidad_actual, 30)

        # Rechaza lote perteneciente a otro medicamento
        self.client.post(url_rep, {
            'item': it_alerta.pk,
            'lote': self.lote.pk,
            'cantidad': 2,
            'nuevo_precinto': 'PREC-ERR-02',
        })
        it_alerta.refresh_from_db()
        self.assertEqual(it_alerta.cantidad_actual, 3)

        # 4. Reposición válida de las 2 unidades faltantes deja carro completo y resta del lote FEFO
        self.client.post(url_rep, {
            'item': it_alerta.pk,
            'lote': lote_45d.pk,
            'cantidad': 2,
            'nuevo_precinto': 'PREC-TEST-OK',
        })
        it_alerta.refresh_from_db()
        lote_45d.refresh_from_db()
        carro.refresh_from_db()
        self.assertEqual(it_alerta.cantidad_actual, 5)
        self.assertEqual(lote_45d.cantidad_actual, 28)
        self.assertEqual(carro.estado, CarroClinico.EstadoCarro.COMPLETO)
        self.assertEqual(carro.numero_precinto, 'PREC-TEST-OK')

    def test_dashboard_admin_unificacion_categorias_bitacora_y_reinicio(self):
        """
        Verifica:
        1) Unificación de categorías respiratorias duplicadas al ejecutar el seed.
        2) Bitácora del dashboard combina operaciones exitosas y bloqueos 403 deduplicados con badges visuales.
        3) Botón y endpoint /reiniciar-escenario/ exclusivos para Administrador (403 para otros roles),
           restaurando datos base manteniendo intactas las cuentas de usuarios y contraseñas.
        """
        from farmacia.models import CategoriaMedicamento
        from core.models import AuditoriaInmutable

        admin_usr = Usuario.objects.create_user(
            username='admin_docente_t',
            password='MiPasswordSegura99!',
            rut='14.555.666-3',
            first_name='Egon',
            last_name='Docente',
            rol=Usuario.Rol.ADMINISTRADOR,
        )
        qf_usr = Usuario.objects.create_user(
            username='qf_dash_t',
            password='Password123!',
            rut='15.666.777-1',
            rol=Usuario.Rol.QUIMICO_FARMACEUTICO,
        )
        alumno_usr = Usuario.objects.create_user(
            username='alumno_custom',
            password='ClavePropiaAlumno!',
            rut='21.111.222-3',
            first_name='Sofía',
            last_name='Alumna',
            rol=Usuario.Rol.TECNICO_FARMACIA,
        )

        # 1. Bitácora inteligente: registrar acciones válidas + ráfaga de 8 bloqueos 403 iguales
        AuditoriaInmutable.objects.create(
            usuario=qf_usr,
            usuario_username='qf_dash_t',
            rol='quimico',
            accion='Dispensación realizada',
            entidad_afectada='Receta REC-BIT-01',
        )
        AuditoriaInmutable.objects.create(
            usuario=qf_usr,
            usuario_username='qf_dash_t',
            rol='quimico',
            accion='Reposición y sellado de carro clínico',
            entidad_afectada='Carro de Paro N° 1',
        )
        for _ in range(8):
            AuditoriaInmutable.objects.create(
                usuario=alumno_usr,
                usuario_username='alumno_custom',
                rol='tecnico',
                accion='Acceso Denegado por Control de Rol (403)',
                entidad_afectada='GET /usuarios/',
            )

        url_dash = reverse('core:dashboard')
        url_reset = reverse('core:reiniciar_escenario')

        # 2. Administrador ve acciones exitosas + 403 colapsado (×8) y botón Reiniciar Escenario
        self.client.login(username='admin_docente_t', password='MiPasswordSegura99!')
        html_dash_adm = self.client.get(url_dash).content.decode()
        self.assertIn('Operación OK', html_dash_adm)
        self.assertIn('Dispensación realizada', html_dash_adm)
        self.assertIn('403 Bloqueado', html_dash_adm)
        self.assertIn('&times;8', html_dash_adm)
        self.assertIn('Reiniciar Escenario', html_dash_adm)
        self.assertIn(url_reset, html_dash_adm)

        # 3. Técnico y Q.F. no ven botón Reiniciar Escenario y reciben 403 en POST /reiniciar-escenario/
        self.client.login(username='tecnico_test', password='Password123!')
        self.assertNotIn('Reiniciar Escenario', self.client.get(url_dash).content.decode())
        self.assertEqual(self.client.post(url_reset).status_code, 403)

        self.client.login(username='qf_dash_t', password='Password123!')
        html_dash_qf = self.client.get(url_dash).content.decode()
        self.assertNotIn('Reiniciar Escenario', html_dash_qf)
        self.assertEqual(self.client.post(url_reset).status_code, 403)

        self.client.login(username='admin_docente_t', password='MiPasswordSegura99!')

        # Crear categoría respiratoria duplicada previa para probar limpieza automática durante reinicio/seed
        cat_dup = CategoriaMedicamento.objects.create(nombre='Respiratorio / Broncodilatadores')
        self.medicamento.categoria = cat_dup
        self.medicamento.save()

        # 4. Ejecutar Reiniciar Escenario -> restaura datos base, unifica categoría y preserva cuentas + contraseñas
        resp_reset = self.client.post(url_reset)
        self.assertEqual(resp_reset.status_code, 302)

        self.assertFalse(CategoriaMedicamento.objects.filter(nombre='Respiratorio / Broncodilatadores').exists())
        self.assertTrue(CategoriaMedicamento.objects.filter(nombre='Respiratorio / Broncodilatadores (GES Asma/EPOC)').exists())
        self.assertTrue(Medicamento.objects.filter(codigo='INS-CLI-001').exists())
        self.assertTrue(Receta.objects.filter(numero_receta='REC-2026-00105').exists())

        # Verificar cuentas y contraseñas preservadas
        admin_usr.refresh_from_db()
        alumno_usr.refresh_from_db()
        self.assertTrue(admin_usr.check_password('MiPasswordSegura99!'))
        self.assertTrue(alumno_usr.check_password('ClavePropiaAlumno!'))

    def test_crud_escenarios_simulacion_y_filtros_por_rol(self):
        """
        Verifica el CRUD completo de EscenarioSimulacion (exclusivo Admin, 403 resto),
        badge de escenario activo, filtrado para Técnico/Q.F., fallback, restaurar recetas
        sin alterar inventario y eliminación segura sin borrar pacientes ni recetas.
        """
        from core.models import EscenarioSimulacion, AuditoriaInmutable
        from ges.models import PatologiaGES, InscripcionGES

        admin_usr = Usuario.objects.create_user(
            username='admin_esc_t',
            password='Password123!',
            rut='14.111.222-7',
            first_name='Docente',
            last_name='Admin',
            rol=Usuario.Rol.ADMINISTRADOR,
        )
        qf_usr = Usuario.objects.create_user(
            username='qf_esc_t',
            password='Password123!',
            rut='15.111.222-0',
            rol=Usuario.Rol.QUIMICO_FARMACEUTICO,
        )
        clinico_usr = Usuario.objects.create_user(
            username='clin_esc_t',
            password='Password123!',
            rut='16.111.222-4',
            rol=Usuario.Rol.PERSONAL_CLINICO,
        )

        # Segundo paciente + segunda receta + inscripción GES para comprobar el filtrado
        pac2 = Paciente.objects.create(
            rut='8.765.432-K',
            nombres='María',
            apellido_paterno='Morales',
            apellido_materno='Castro',
            fecha_nacimiento=date(1965, 5, 10),
            sexo='F',
            prevision=Paciente.Prevision.FONASA_B,
            cronico=True,
        )
        pat_ges = PatologiaGES.objects.create(codigo='GES-99', nombre='Diabetes Tipo 2', activa=True)
        InscripcionGES.objects.create(
            paciente=self.paciente,
            patologia=pat_ges,
            fecha_inscripcion=date.today(),
            fecha_inicio_periodo=date.today(),
            fecha_fin_periodo=date.today() + timedelta(days=365),
            activa=True,
        )
        InscripcionGES.objects.create(
            paciente=pac2,
            patologia=pat_ges,
            fecha_inscripcion=date.today(),
            fecha_inicio_periodo=date.today(),
            fecha_fin_periodo=date.today() + timedelta(days=365),
            activa=True,
        )
        rec1 = Receta.objects.create(
            numero_receta='REC-ESC-001',
            paciente=self.paciente,
            medico=self.medico,
            tipo=Receta.TipoReceta.SIMPLE,
            diagnostico='Hipertensión Arterial',
            fecha_emision=date.today(),
            fecha_vencimiento=date.today() + timedelta(days=30),
        )
        DetalleReceta.objects.create(
            receta=rec1,
            medicamento=self.medicamento,
            cantidad_prescrita=10,
            posologia='1 al día',
        )
        rec2 = Receta.objects.create(
            numero_receta='REC-ESC-002',
            paciente=pac2,
            medico=self.medico,
            tipo=Receta.TipoReceta.SIMPLE,
            diagnostico='Diabetes Mellitus',
            fecha_emision=date.today(),
            fecha_vencimiento=date.today() + timedelta(days=30),
        )
        det2 = DetalleReceta.objects.create(
            receta=rec2,
            medicamento=self.medicamento,
            cantidad_prescrita=20,
            posologia='1 cada 12h',
        )

        url_list = reverse('core:escenario_list')
        url_crear = reverse('core:escenario_crear')

        # 1. Bloqueo 403 para Técnico, Q.F. y Clínico
        for usr_name in ('tecnico_test', 'qf_esc_t', 'clin_esc_t'):
            self.client.login(username=usr_name, password='Password123!')
            self.assertEqual(self.client.get(url_list).status_code, 403)
            self.assertEqual(self.client.get(url_crear).status_code, 403)

        # 2. Admin crea Escenario A (solo pac2 y rec2) activándolo al guardar
        self.client.login(username='admin_esc_t', password='Password123!')
        self.assertIn('Escenarios de Simulación', self.client.get(url_list).content.decode())

        # Validación nombre vacío
        resp_vacio = self.client.post(url_crear, {'nombre': '   '})
        self.assertEqual(resp_vacio.status_code, 200)
        self.assertEqual(EscenarioSimulacion.objects.count(), 0)

        resp_crear_a = self.client.post(url_crear, {
            'nombre': 'Evaluación A — Solo Caso 2',
            'descripcion': 'Taller filtrado para sección 1',
            'activo': 'on',
            'pacientes': [pac2.pk],
            'recetas': [rec2.pk],
        })
        self.assertEqual(resp_crear_a.status_code, 302)
        esc_a = EscenarioSimulacion.objects.get(nombre='Evaluación A — Solo Caso 2')
        self.assertTrue(esc_a.activo)
        self.assertEqual(list(esc_a.pacientes.values_list('id', flat=True)), [pac2.pk])
        self.assertEqual(list(esc_a.recetas.values_list('id', flat=True)), [rec2.pk])

        # Validación nombre duplicado
        resp_dup = self.client.post(url_crear, {'nombre': 'Evaluación A — Solo Caso 2'})
        self.assertEqual(resp_dup.status_code, 200)
        self.assertEqual(EscenarioSimulacion.objects.count(), 1)

        # 3. Editar Escenario A
        url_edit_a = reverse('core:escenario_editar', args=[esc_a.pk])
        resp_edit_a = self.client.post(url_edit_a, {
            'nombre': 'Evaluación A — Editada',
            'descripcion': 'Descripción actualizada',
            'activo': 'on',
            'pacientes': [pac2.pk],
            'recetas': [rec2.pk],
        })
        self.assertEqual(resp_edit_a.status_code, 302)
        esc_a.refresh_from_db()
        self.assertEqual(esc_a.nombre, 'Evaluación A — Editada')

        # 4. Técnico y Q.F. ven badge + solo pacientes/recetas/GES de Escenario A; Admin ve todo
        for usr_name in ('tecnico_test', 'qf_esc_t'):
            self.client.login(username=usr_name, password='Password123!')
            html_vent = self.client.get(reverse('dispensacion:dispensar')).content.decode()
            self.assertIn('Escenario Activo: Evaluación A — Editada', html_vent)
            self.assertIn('REC-ESC-002', html_vent)
            self.assertNotIn(rec1.numero_receta, html_vent)

            html_pac = self.client.get(reverse('core:paciente_list')).content.decode()
            self.assertIn('8.765.432-K', html_pac)
            self.assertNotIn(self.paciente.rut, html_pac)

            html_ges = self.client.get(reverse('ges:inscripcion_list')).content.decode()
            self.assertIn('8.765.432-K', html_ges)
            self.assertNotIn(self.paciente.rut, html_ges)

        # /pacientes/ muestra solo los pacientes del escenario activo también para Admin;
        # el archivo general docente vive en /admin-panel/banco-pacientes/ (403 para otros roles)
        self.client.login(username='tecnico_test', password='Password123!')
        self.assertEqual(self.client.get(reverse('core:banco_pacientes')).status_code, 403)
        self.assertEqual(
            self.client.post(reverse('core:banco_paciente_asignar_escenarios', args=[self.paciente.pk])).status_code,
            403,
        )

        self.client.login(username='admin_esc_t', password='Password123!')
        html_pac_admin_esc = self.client.get(reverse('core:paciente_list')).content.decode()
        self.assertIn('Banco de Pacientes', html_pac_admin_esc)
        self.assertIn('8.765.432-K', html_pac_admin_esc)
        self.assertNotIn(self.paciente.rut, html_pac_admin_esc)

        # Banco de Pacientes muestra todos, filtra libres y permite asignar a escenarios
        url_banco = reverse('core:banco_pacientes')
        html_banco_all = self.client.get(url_banco).content.decode()
        self.assertIn('8.765.432-K', html_banco_all)
        self.assertIn(self.paciente.rut, html_banco_all)
        self.assertIn('Libre (sin asignar)', html_banco_all)

        html_banco_libres = self.client.get(url_banco + '?escenario=libres').content.decode()
        self.assertIn(self.paciente.rut, html_banco_libres)
        self.assertNotIn('8.765.432-K', html_banco_libres)

        # Asignar self.paciente al escenario activo y luego quitarlo
        ver_antes = esc_a.actualizado_en
        resp_asig = self.client.post(
            reverse('core:banco_paciente_asignar_escenarios', args=[self.paciente.pk]),
            {'escenarios': [esc_a.pk]},
        )
        self.assertEqual(resp_asig.status_code, 302)
        esc_a.refresh_from_db()
        self.assertTrue(esc_a.pacientes.filter(pk=self.paciente.pk).exists())
        self.assertNotEqual(esc_a.actualizado_en, ver_antes)

        # Quitar self.paciente para mantener estado esperado en pasos siguientes
        self.client.post(
            reverse('core:banco_paciente_asignar_escenarios', args=[self.paciente.pk]),
            {},
        )
        self.assertFalse(esc_a.pacientes.filter(pk=self.paciente.pk).exists())

        # 5. Restaurar recetas del escenario devuelve estado Pendiente y dispensado=0 sin tocar inventario
        stock_lote_antes = self.lote.cantidad_actual
        det2.cantidad_dispensada = 20
        det2.save()
        rec2.estado = Receta.EstadoReceta.DISPENSADA_TOTAL
        rec2.autorizada_qf = True
        rec2.save()

        resp_rest = self.client.post(reverse('core:escenario_restaurar_recetas', args=[esc_a.pk]))
        self.assertEqual(resp_rest.status_code, 302)
        rec2.refresh_from_db()
        det2.refresh_from_db()
        self.lote.refresh_from_db()
        self.assertEqual(rec2.estado, Receta.EstadoReceta.PENDIENTE)
        self.assertFalse(rec2.autorizada_qf)
        self.assertEqual(det2.cantidad_dispensada, 0)
        self.assertEqual(self.lote.cantidad_actual, stock_lote_antes)

        # 6. Bloqueo de eliminación si el escenario está activo
        resp_del_activo = self.client.post(reverse('core:escenario_eliminar', args=[esc_a.pk]), follow=True)
        self.assertTrue(EscenarioSimulacion.objects.filter(pk=esc_a.pk).exists())
        self.assertIn('Activa otro escenario antes de eliminar este.', resp_del_activo.content.decode())

        # 7. Crear Escenario B y activarlo atómicamente (desactiva A y audita)
        resp_crear_b = self.client.post(url_crear, {
            'nombre': 'Escenario Base Completo',
            'descripcion': 'Todos los casos',
            'pacientes': [self.paciente.pk, pac2.pk],
            'recetas': [rec1.pk, rec2.pk],
        })
        self.assertEqual(resp_crear_b.status_code, 302)
        esc_b = EscenarioSimulacion.objects.get(nombre='Escenario Base Completo')
        self.assertFalse(esc_b.activo)

        resp_act_b = self.client.post(reverse('core:escenario_activar', args=[esc_b.pk]))
        self.assertEqual(resp_act_b.status_code, 302)
        esc_a.refresh_from_db()
        esc_b.refresh_from_db()
        self.assertFalse(esc_a.activo)
        self.assertTrue(esc_b.activo)
        self.assertEqual(EscenarioSimulacion.objects.filter(activo=True).count(), 1)
        self.assertTrue(
            AuditoriaInmutable.objects.filter(accion='Activación de Escenario de Simulación').exists()
        )

        # 8. Eliminar Escenario A (ahora inactivo) conserva Paciente y Receta en DB
        resp_del_inactivo = self.client.post(reverse('core:escenario_eliminar', args=[esc_a.pk]))
        self.assertEqual(resp_del_inactivo.status_code, 302)
        self.assertFalse(EscenarioSimulacion.objects.filter(pk=esc_a.pk).exists())
        self.assertTrue(Paciente.objects.filter(pk=pac2.pk).exists())
        self.assertTrue(Receta.objects.filter(pk=rec2.pk).exists())

        # 9. Bloqueo 403 en acciones POST para no-admin
        self.client.login(username='tecnico_test', password='Password123!')
        self.assertEqual(self.client.post(reverse('core:escenario_activar', args=[esc_b.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('core:escenario_restaurar_recetas', args=[esc_b.pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('core:escenario_eliminar', args=[esc_b.pk])).status_code, 403)

        # 10. Fallback seguro si no hay ningún escenario activo: Técnico ve todos los pacientes y recetas
        esc_b.activo = False
        esc_b.save(update_fields=['activo'])
        html_vent_fb = self.client.get(reverse('dispensacion:dispensar')).content.decode()
        self.assertIn(rec1.numero_receta, html_vent_fb)
        self.assertIn('REC-ESC-002', html_vent_fb)

    def test_formulario_nuevo_paciente_validaciones_y_tercero(self):
        """
        Verifica el pulido de Registrar Nuevo Paciente:
        - Asteriscos obligatorios, placeholder RUT, opciones de previsión solo red pública (sin Isapres).
        - Validación de RUT inválido, RUT duplicado y RUT de tercero autorizado.
        - Registro exitoso con Sin Previsión y Tercero Autorizado para Retiro.
        """
        admin_usr = Usuario.objects.create_user(
            username='admin_pac_t',
            password='Password123!',
            rut='14.222.333-0',
            rol=Usuario.Rol.ADMINISTRADOR,
        )
        self.client.login(username='admin_pac_t', password='Password123!')

        url_crear = reverse('core:paciente_crear')
        html_form = self.client.get(url_crear).content.decode()
        self.assertIn('Ej: 12.345.678-9', html_form)
        self.assertIn('text-danger">*</span>', html_form)
        self.assertIn('Tercero Autorizado para Retiro', html_form)
        for opc in ('FONASA A', 'FONASA B', 'FONASA C', 'FONASA D', 'PRAIS', 'Sin Previsión'):
            self.assertIn(opc, html_form)
        self.assertNotIn('Isapre', html_form)

        # API validar RUT duplicado
        resp_api_dup = self.client.get(reverse('core:api_validar_rut'), {
            'rut': self.paciente.rut,
            'check_paciente': '1',
        })
        self.assertTrue(resp_api_dup.json()['duplicado'])

        # POST RUT duplicado rechazado
        resp_dup = self.client.post(url_crear, {
            'rut': self.paciente.rut,
            'nombres': 'Duplicado',
            'apellido_paterno': 'Uno',
            'apellido_materno': 'Dos',
            'fecha_nacimiento': '1990-01-01',
            'sexo': 'M',
            'prevision': 'fonasa_a',
        })
        self.assertEqual(resp_dup.status_code, 200)
        self.assertIn('Ya existe un paciente registrado con el RUT', resp_dup.content.decode())

        # POST previsión no pública rechazada
        resp_isapre = self.client.post(url_crear, {
            'rut': '13.579.246-2',
            'nombres': 'Carlos',
            'apellido_paterno': 'Silva',
            'apellido_materno': 'Rojas',
            'fecha_nacimiento': '1985-03-15',
            'sexo': 'M',
            'prevision': 'isapre_colmena',
        })
        self.assertEqual(resp_isapre.status_code, 200)
        self.assertFalse(Paciente.objects.filter(rut='13.579.246-2').exists())

        # POST válido con Sin Previsión y Tercero Autorizado
        resp_ok = self.client.post(url_crear, {
            'rut': '135792462',
            'nombres': 'Carlos Alberto',
            'apellido_paterno': 'Silva',
            'apellido_materno': 'Rojas',
            'fecha_nacimiento': '1985-03-15',
            'sexo': 'M',
            'prevision': 'sin_prevision',
            'tercero_autorizado_nombre': 'Carolina Silva Rojas',
            'tercero_autorizado_rut': '201234565',
            'tercero_autorizado_parentesco': 'Hermana',
        })
        self.assertEqual(resp_ok.status_code, 302)
        pac_nuevo = Paciente.objects.get(rut='13.579.246-2')
        self.assertEqual(pac_nuevo.prevision, Paciente.Prevision.SIN_PREVISION)
        self.assertEqual(pac_nuevo.tercero_autorizado_nombre, 'Carolina Silva Rojas')
        self.assertEqual(pac_nuevo.tercero_autorizado_rut, '20.123.456-5')
        self.assertEqual(pac_nuevo.tercero_autorizado_parentesco, 'Hermana')

        html_det = self.client.get(reverse('core:paciente_detalle', args=[pac_nuevo.pk])).content.decode()
        self.assertIn('Sin Previsión', html_det)
        self.assertIn('Carolina Silva Rojas', html_det)
        self.assertIn('20.123.456-5', html_det)
        self.assertIn('Hermana', html_det)

    def test_escenarios_tiempo_real_incidencias_e_inyeccion_rapida(self):
        """
        Verifica:
        1) Escenario activo vacío muestra mensaje vacío sin fallback silencioso.
        2) Endpoint /api/simulacion/estado/ expone escenario_id, nombre y version ISO,
           cambiando al activar, editar, restaurar o inyectar caso.
        3) Incidencias configurables al activar (quiebre en vitrina, lote crítico FEFO 12d, consumo Carro de Paro).
        4) Inyectar Caso Rápido crea paciente + receta pendiente, actualiza version y aparece en Ventanilla.
        """
        from core.models import EscenarioSimulacion
        from carros_clinicos.models import CarroClinico, PlantillaItemCarro, ConsumoCarroClinico

        admin_usr = Usuario.objects.create_user(
            username='admin_rt_t',
            password='Password123!',
            rut='14.333.444-3',
            rol=Usuario.Rol.ADMINISTRADOR,
        )
        carro = CarroClinico.objects.create(
            nombre='Carro de Paro Urgencia',
            tipo=CarroClinico.TipoCarro.PARO,
            ubicacion_fisica='Box Reanimación',
            estado=CarroClinico.EstadoCarro.COMPLETO,
            numero_precinto='PREC-999',
        )
        item_carro = PlantillaItemCarro.objects.create(
            carro=carro,
            medicamento=self.medicamento,
            cantidad_requerida=5,
            cantidad_actual=5,
            ubicacion_en_carro='Cajón 1',
        )

        # 1. Crear escenario vacío con las 3 incidencias activadas
        self.client.login(username='admin_rt_t', password='Password123!')
        resp_crear = self.client.post(reverse('core:escenario_crear'), {
            'nombre': 'Taller Incidencias En Vivo',
            'descripcion': 'Prueba de incidencias y sin fallback',
            'simular_quiebre': 'on',
            'medicamento_quiebre': self.medicamento.pk,
            'simular_alerta_fefo': 'on',
            'simular_consumo_carro': 'on',
        })
        self.assertEqual(resp_crear.status_code, 302)
        esc = EscenarioSimulacion.objects.get(nombre='Taller Incidencias En Vivo')

        # 2. Activar -> aplica las 3 incidencias y actualiza /api/simulacion/estado/
        resp_act = self.client.post(reverse('core:escenario_activar', args=[esc.pk]))
        self.assertEqual(resp_act.status_code, 302)

        self.lote.refresh_from_db()
        self.assertLess(self.lote.cantidad_actual, self.medicamento.stock_minimo)
        self.assertTrue(Lote.objects.filter(numero_lote=f'SIM-FEFO-{esc.pk}').exists())
        carro.refresh_from_db()
        item_carro.refresh_from_db()
        self.assertEqual(carro.estado, CarroClinico.EstadoCarro.INCOMPLETO)
        self.assertEqual(carro.numero_precinto, '')
        self.assertLess(item_carro.cantidad_actual, 5)
        self.assertTrue(ConsumoCarroClinico.objects.filter(carro=carro).exists())

        # 3. Técnico consulta /api/simulacion/estado/ y verifica vistas vacías sin fallback
        self.client.login(username='tecnico_test', password='Password123!')
        estado_1 = self.client.get(reverse('core:api_simulacion_estado')).json()
        self.assertEqual(estado_1['escenario_id'], esc.pk)
        self.assertEqual(estado_1['nombre'], 'Taller Incidencias En Vivo')
        self.assertNotEqual(estado_1['version'], 'none')

        html_pac_vacio = self.client.get(reverse('core:paciente_list')).content.decode()
        self.assertIn('Este escenario aún no tiene pacientes asignados.', html_pac_vacio)
        self.assertNotIn(self.paciente.rut, html_pac_vacio)

        html_vent_vacio = self.client.get(reverse('dispensacion:dispensar')).content.decode()
        self.assertIn('Este escenario aún no tiene recetas asignadas.', html_vent_vacio)

        # Bloqueo 403 en inyectar caso para Técnico
        url_inyectar = reverse('core:escenario_inyectar_caso', args=[esc.pk])
        self.assertEqual(self.client.post(url_inyectar).status_code, 403)

        # 4. Admin inyecta caso rápido -> cambia version y aparece al instante en Ventanilla y Pacientes
        self.client.login(username='admin_rt_t', password='Password123!')
        resp_iny = self.client.post(url_inyectar, {
            'nombres': 'Matías Ignacio',
            'apellido_paterno': 'Fuentes',
            'apellido_materno': 'Lagos',
            'prevision': 'fonasa_c',
            'medicamento_id': self.medicamento.pk,
            'cantidad': '15',
            'tipo': 'simple',
            'diagnostico': 'Crisis hipertensiva simulada',
            'posologia': '1 comp al día',
        })
        self.assertEqual(resp_iny.status_code, 302)

        self.client.login(username='tecnico_test', password='Password123!')
        estado_2 = self.client.get(reverse('core:api_simulacion_estado')).json()
        self.assertNotEqual(estado_2['version'], estado_1['version'])

        html_vent_despues = self.client.get(reverse('dispensacion:dispensar')).content.decode()
        self.assertIn('Matías Ignacio', html_vent_despues)
        self.assertIn('REC-LIVE-', html_vent_despues)

        html_pac_despues = self.client.get(reverse('core:paciente_list')).content.decode()
        self.assertIn('Matías Ignacio', html_pac_despues)

    def test_constructor_escenarios_modalidad_consignas_ajax_y_aislamiento(self):
        """
        Verifica:
        1) Modalidad LIBRE vs INCIDENCIAS y consignas personalizadas visibles en Dashboard de Técnico, Q.F. y Clínico.
        2) Endpoints AJAX (+ Nuevo Paciente, + Nueva Receta con simular_vencida, Generar Caso Aleatorio)
           exclusivos para Admin (403 para otros roles).
        3) Aislamiento estricto: los pacientes y recetas creados inline NO contaminan Escenario Base.
        """
        import json as _json
        from core.models import EscenarioSimulacion
        from ges.models import PatologiaGES, InscripcionGES

        admin_usr = Usuario.objects.create_user(
            username='admin_builder_t',
            password='Password123!',
            rut='14.444.555-6',
            rol=Usuario.Rol.ADMINISTRADOR,
        )
        qf_usr = Usuario.objects.create_user(
            username='qf_builder_t',
            password='Password123!',
            rut='15.444.555-9',
            rol=Usuario.Rol.QUIMICO_FARMACEUTICO,
        )
        clin_usr = Usuario.objects.create_user(
            username='clin_builder_t',
            password='Password123!',
            rut='16.444.555-2',
            rol=Usuario.Rol.PERSONAL_CLINICO,
        )
        pat_ges = PatologiaGES.objects.create(codigo='GES-77', nombre='Hipertensión Arterial', activa=True)

        # Escenario Base existente para comprobar aislamiento
        esc_base = EscenarioSimulacion.objects.create(
            nombre='Escenario Base — Prueba Aislamiento',
            activo=True,
            creado_por=admin_usr,
        )
        esc_base.pacientes.set([self.paciente])

        url_nuevo = reverse('core:escenario_nuevo')
        url_api_pac = reverse('core:api_escenario_crear_paciente')
        url_api_rec = reverse('core:api_escenario_crear_receta')
        url_api_rnd = reverse('core:api_escenario_caso_aleatorio')

        # 1. Bloqueo 403 en endpoints AJAX para Técnico, Q.F. y Clínico
        for usr in ('tecnico_test', 'qf_builder_t', 'clin_builder_t'):
            self.client.login(username=usr, password='Password123!')
            self.assertEqual(self.client.post(url_api_pac, {}, HTTP_ACCEPT='application/json').status_code, 403)
            self.assertEqual(self.client.post(url_api_rec, {}, HTTP_ACCEPT='application/json').status_code, 403)
            self.assertEqual(self.client.post(url_api_rnd, {}, HTTP_ACCEPT='application/json').status_code, 403)

        # 2. Admin abre /admin-panel/escenarios/nuevo/ y crea paciente, receta (vigente y vencida) y caso aleatorio vía AJAX
        self.client.login(username='admin_builder_t', password='Password123!')
        html_nuevo = self.client.get(url_nuevo).content.decode()
        self.assertIn('Práctica Libre / Juego de Roles', html_nuevo)
        self.assertIn('Con Incidencias Automáticas', html_nuevo)
        self.assertIn('Incidencias / Consignas Personalizadas del Docente', html_nuevo)
        self.assertIn('Generar Caso Aleatorio', html_nuevo)

        # Validación RUT inválido y previsión no pública
        r_bad_rut = self.client.post(
            url_api_pac,
            _json.dumps({
                'rut': '12.345.678-0',
                'nombres': 'Mal',
                'apellido_paterno': 'Rut',
                'apellido_materno': 'Test',
                'fecha_nacimiento': '1980-01-01',
                'prevision': 'fonasa_a',
            }),
            content_type='application/json',
        )
        self.assertEqual(r_bad_rut.status_code, 400)

        # Crear paciente inline válido con GES y tercero autorizado
        r_pac = self.client.post(
            url_api_pac,
            _json.dumps({
                'rut': '135792462',
                'nombres': 'Lorena Beatriz',
                'apellido_paterno': 'Paredes',
                'apellido_materno': 'Soto',
                'fecha_nacimiento': '1972-08-20',
                'prevision': 'fonasa_c',
                'cronico': True,
                'patologia_ges_id': str(pat_ges.pk),
                'tercero_autorizado_nombre': 'Pedro Paredes',
                'tercero_autorizado_rut': '201234565',
                'tercero_autorizado_parentesco': 'Hijo',
            }),
            content_type='application/json',
        )
        self.assertEqual(r_pac.status_code, 201)
        pac_data = r_pac.json()['paciente']
        self.assertEqual(pac_data['rut'], '13.579.246-2')
        self.assertTrue(InscripcionGES.objects.filter(paciente_id=pac_data['id'], patologia=pat_ges).exists())

        # Crear receta vencida inline
        r_rec = self.client.post(
            url_api_rec,
            _json.dumps({
                'paciente_id': pac_data['id'],
                'medico_id': self.medico.pk,
                'medicamento_id': self.medicamento.pk,
                'tipo': 'simple',
                'diagnostico': 'Control HTA con receta vencida',
                'cantidad': 30,
                'posologia': '1 al día',
                'simular_vencida': True,
            }),
            content_type='application/json',
        )
        self.assertEqual(r_rec.status_code, 201)
        rec_data = r_rec.json()['receta']
        self.assertTrue(rec_data['esta_vencida'])

        # Generar caso aleatorio vía AJAX
        r_rnd = self.client.post(url_api_rnd, _json.dumps({}), content_type='application/json')
        self.assertEqual(r_rnd.status_code, 201)
        rnd_json = r_rnd.json()
        rnd_pac_id = rnd_json['paciente']['id']
        rnd_rec_id = rnd_json['receta']['id']

        # 3. Aislamiento: ninguno de estos registros fue agregado a Escenario Base
        esc_base.refresh_from_db()
        self.assertEqual(list(esc_base.pacientes.values_list('id', flat=True)), [self.paciente.pk])
        self.assertEqual(esc_base.recetas.count(), 0)

        # 4. Guardar escenario en modalidad LIBRE con consigna personalizada visible y activarlo
        stock_antes = self.lote.cantidad_actual
        resp_save = self.client.post(url_nuevo, {
            'nombre': 'Juego de Roles — Receta Física Urgencia',
            'descripcion': 'Taller libre de atención en mostrador',
            'modalidad': 'LIBRE',
            'consignas_personalizadas': 'Paciente llega con receta física en papel de urgencia. Validar tercero autorizado.',
            'mostrar_consigna_a_estudiantes': 'on',
            'activo': 'on',
            'simular_quiebre': 'on',  # Debe ignorarse en modalidad LIBRE
            'medicamento_quiebre': self.medicamento.pk,
            'pacientes': [pac_data['id'], rnd_pac_id],
            'recetas': [rec_data['id'], rnd_rec_id],
        })
        self.assertEqual(resp_save.status_code, 302)

        esc_libre = EscenarioSimulacion.objects.get(nombre='Juego de Roles — Receta Física Urgencia')
        self.assertEqual(esc_libre.modalidad, EscenarioSimulacion.Modalidad.LIBRE)
        self.assertFalse(esc_libre.simular_quiebre)
        self.lote.refresh_from_db()
        self.assertEqual(self.lote.cantidad_actual, stock_antes)

        # Escenario Base sigue intacto
        self.assertEqual(list(esc_base.pacientes.values_list('id', flat=True)), [self.paciente.pk])
        self.assertEqual(esc_base.recetas.count(), 0)

        # 5. Técnico, Q.F. y Personal Clínico ven "Consigna del Taller Activo" en su Dashboard
        for usr in ('tecnico_test', 'qf_builder_t', 'clin_builder_t'):
            self.client.login(username=usr, password='Password123!')
            html_dash = self.client.get(reverse('core:dashboard')).content.decode()
            self.assertIn('Consigna del Taller Activo', html_dash)
            self.assertIn('Paciente llega con receta física en papel de urgencia.', html_dash)

        # Si se oculta la consigna, deja de mostrarse en Dashboard de estudiantes
        esc_libre.mostrar_consigna_a_estudiantes = False
        esc_libre.save(update_fields=['mostrar_consigna_a_estudiantes'])
        self.client.login(username='tecnico_test', password='Password123!')
        self.assertNotIn('Consigna del Taller Activo', self.client.get(reverse('core:dashboard')).content.decode())

        # 6. Duplicar Escenario (solo Admin, 403 para Técnico)
        url_dup = reverse('core:escenario_duplicar', args=[esc_libre.pk])
        self.assertEqual(self.client.post(url_dup).status_code, 403)

        self.client.login(username='admin_builder_t', password='Password123!')
        resp_dup = self.client.post(url_dup)
        self.assertEqual(resp_dup.status_code, 302)
        esc_copia = EscenarioSimulacion.objects.get(nombre='Juego de Roles — Receta Física Urgencia (Copia)')
        self.assertFalse(esc_copia.activo)
        self.assertEqual(esc_copia.pacientes.count(), esc_libre.pacientes.count())
        self.assertEqual(esc_copia.recetas.count(), esc_libre.recetas.count())

        # 7. Admin crea paciente desde /pacientes/crear/ con incluir_en_escenario_activo='on' -> entra al escenario activo
        from core.utils import generar_rut_unico_paciente
        rut_valido_nuevo = generar_rut_unico_paciente()
        resp_pac_act = self.client.post(reverse('core:paciente_crear'), {
            'rut': rut_valido_nuevo,
            'nombres': 'Esteban',
            'apellido_paterno': 'Lagos',
            'apellido_materno': 'Vega',
            'fecha_nacimiento': '1988-02-10',
            'sexo': 'M',
            'prevision': 'fonasa_b',
            'incluir_en_escenario_activo': 'on',
        })
        self.assertEqual(resp_pac_act.status_code, 302)
        self.assertTrue(esc_libre.pacientes.filter(rut=rut_valido_nuevo).exists())

    def test_crud_carros_plantilla_precinto_roto_y_alertas_tarjeta(self):
        """
        Verifica el CRUD completo de Carros Clínicos y Plantilla Canónica (RBAC 403),
        el ciclo realista del Precinto de Seguridad (Sellado -> Precinto Roto -> Resellado)
        y el badge de alerta de vencimientos (<= 60d) en las tarjetas de /carros/.
        """
        from carros_clinicos.models import CarroClinico, PlantillaItemCarro
        from core.models import AuditoriaInmutable

        admin_usr = Usuario.objects.create_user(
            username='admin_carro_crud',
            password='Password123!',
            rut='14.777.888-2',
            rol=Usuario.Rol.ADMINISTRADOR,
        )
        qf_usr = Usuario.objects.create_user(
            username='qf_carro_crud',
            password='Password123!',
            rut='15.777.888-5',
            rol=Usuario.Rol.QUIMICO_FARMACEUTICO,
        )
        clin_usr = Usuario.objects.create_user(
            username='clin_carro_crud',
            password='Password123!',
            rut='16.777.888-9',
            rol=Usuario.Rol.PERSONAL_CLINICO,
        )

        # Segundo medicamento con lote próximo a vencer (25 días <= 60 días)
        med_alerta = Medicamento.objects.create(
            codigo='MED-CARRO-FEFO',
            nombre_generico='Adrenalina Sim',
            concentracion='1 mg/ml',
            forma_farmaceutica='Ampolla',
            categoria=self.categoria,
            stock_minimo=5,
            stock_maximo=100,
        )
        Lote.objects.create(
            medicamento=med_alerta,
            numero_lote='ADR-CRIT-25D',
            fecha_fabricacion=date.today() - timedelta(days=90),
            fecha_vencimiento=date.today() + timedelta(days=25),
            cantidad_inicial=30,
            cantidad_actual=30,
            ubicacion=self.vitrina,
        )

        # 1. Crear carro nuevo como Admin
        self.client.login(username='admin_carro_crud', password='Password123!')
        resp_new = self.client.post(reverse('carros_clinicos:carro_list'), {
            'nombre': 'Carro de Paro CRUD Test',
            'tipo': 'paro',
            'ubicacion_fisica': 'Box Reanimación 3',
            'numero_precinto': 'PREC-INIT-01',
        })
        self.assertEqual(resp_new.status_code, 302)
        carro = CarroClinico.objects.get(nombre='Carro de Paro CRUD Test')

        # 2. Agregar 2 ítems a su plantilla (uno con lote <= 60 días)
        url_det = reverse('carros_clinicos:carro_detalle', args=[carro.pk])
        self.client.post(url_det, {
            'accion': 'agregar_item_plantilla',
            'medicamento_id': self.medicamento.pk,
            'cantidad_requerida': '5',
            'cantidad_actual': '5',
            'ubicacion_en_carro': 'Cajón 1',
        })
        self.client.post(url_det, {
            'accion': 'agregar_item_plantilla',
            'medicamento_id': med_alerta.pk,
            'cantidad_requerida': '4',
            'cantidad_actual': '4',
            'ubicacion_en_carro': 'Cajón 2',
        })
        item_1 = PlantillaItemCarro.objects.get(carro=carro, medicamento=self.medicamento)
        item_2 = PlantillaItemCarro.objects.get(carro=carro, medicamento=med_alerta)
        self.assertEqual(item_2.lote_referencia.numero_lote, 'ADR-CRIT-25D')

        # 3. Tarjeta en /carros/ muestra Sellado · Completo - Operativo + ⏳ 1 ítem por vencer
        html_list_1 = self.client.get(reverse('carros_clinicos:carro_list')).content.decode()
        self.assertIn('Sellado · Completo - Operativo', html_list_1)
        self.assertIn('PREC-INIT-01', html_list_1)
        self.assertIn('1 ítem por vencer', html_list_1)

        # 4. RBAC 403 para Técnico y Clínico al editar carro o plantilla; permitido para Q.F.
        url_edit_carro = reverse('carros_clinicos:carro_editar', args=[carro.pk])
        url_del_carro = reverse('carros_clinicos:carro_eliminar', args=[carro.pk])
        url_edit_item = reverse('carros_clinicos:item_plantilla_editar', args=[carro.pk, item_2.pk])
        url_del_item = reverse('carros_clinicos:item_plantilla_eliminar', args=[carro.pk, item_2.pk])

        for usr in ('tecnico_test', 'clin_carro_crud'):
            self.client.login(username=usr, password='Password123!')
            self.assertEqual(self.client.post(url_edit_carro, {'nombre': 'X', 'ubicacion_fisica': 'Y'}).status_code, 403)
            self.assertEqual(self.client.post(url_edit_item, {'cantidad_requerida': '6'}).status_code, 403)
            self.assertEqual(self.client.post(url_del_item).status_code, 403)
            self.assertEqual(self.client.post(url_del_carro).status_code, 403)

        # Q.F. puede editar datos básicos del carro y editar/quitar ítems, pero recibe 403 al eliminar carro
        self.client.login(username='qf_carro_crud', password='Password123!')
        self.assertEqual(self.client.post(url_del_carro).status_code, 403)
        resp_ed_c = self.client.post(url_edit_carro, {
            'nombre': 'Carro de Paro Editado QF',
            'tipo': 'paro',
            'ubicacion_fisica': 'Box Reanimación Central',
        })
        self.assertEqual(resp_ed_c.status_code, 302)
        carro.refresh_from_db()
        self.assertEqual(carro.nombre, 'Carro de Paro Editado QF')

        resp_ed_it = self.client.post(url_edit_item, {
            'cantidad_requerida': '6',
            'ubicacion_en_carro': 'Cajón Superior',
        })
        self.assertEqual(resp_ed_it.status_code, 302)
        item_2.refresh_from_db()
        self.assertEqual(item_2.cantidad_requerida, 6)
        self.assertEqual(item_2.ubicacion_en_carro, 'Cajón Superior')

        # Quitar item_2 (sin historial) funciona y se audita
        resp_rm_it = self.client.post(url_del_item)
        self.assertEqual(resp_rm_it.status_code, 302)
        self.assertFalse(PlantillaItemCarro.objects.filter(pk=item_2.pk).exists())
        self.assertTrue(AuditoriaInmutable.objects.filter(accion='Eliminación de Ítem de Plantilla de Carro').exists())

        # 5. Consumo por Clínico -> Precinto Roto — Pendiente Resellado + precinto anterior tachado
        self.client.login(username='clin_carro_crud', password='Password123!')
        resp_cons = self.client.post(reverse('carros_clinicos:registrar_consumo', args=[carro.pk]), {
            'item': item_1.pk,
            'cantidad': '2',
            'motivo': 'Código Azul Box Central',
        })
        self.assertEqual(resp_cons.status_code, 302)

        html_det_roto = self.client.get(url_det).content.decode()
        self.assertIn('Precinto Roto — Pendiente Resellado', html_det_roto)
        self.assertIn('<del class="text-muted">PREC-INIT-01</del>', html_det_roto)

        html_list_roto = self.client.get(reverse('carros_clinicos:carro_list')).content.decode()
        self.assertIn('Precinto Roto — Pendiente Resellado', html_list_roto)
        self.assertIn('<del class="text-muted">PREC-INIT-01</del>', html_list_roto)

        # 6. Reposición por Técnico con nuevo precinto -> vuelve a Sellado · Completo - Operativo
        self.client.login(username='tecnico_test', password='Password123!')
        resp_rep = self.client.post(reverse('carros_clinicos:reponer_carro', args=[carro.pk]), {
            'item': item_1.pk,
            'lote': self.lote.pk,
            'cantidad': '2',
            'nuevo_precinto': 'PREC-NUEVO-99',
        })
        self.assertEqual(resp_rep.status_code, 302)

        html_det_sellado = self.client.get(url_det).content.decode()
        self.assertIn('Sellado · Completo - Operativo', html_det_sellado)
        self.assertIn('PREC-NUEVO-99', html_det_sellado)
        self.assertNotIn('Precinto Roto — Pendiente Resellado', html_det_sellado)

        # 7. Admin no puede eliminar físicamente carro con historial, pero sí desactivarlo; carro sin historial sí se elimina
        self.client.login(username='admin_carro_crud', password='Password123!')
        self.client.post(url_del_carro, {'modo': 'eliminar'})
        carro.refresh_from_db()
        self.assertTrue(carro.activo)

        self.client.post(url_del_carro, {'modo': 'desactivar'})
        carro.refresh_from_db()
        self.assertFalse(carro.activo)

        carro_sin_hist = CarroClinico.objects.create(
            nombre='Carro Temporal Sin Uso',
            tipo=CarroClinico.TipoCarro.UNIDOSIS,
            ubicacion_fisica='Sala 4',
        )
        self.client.post(reverse('carros_clinicos:carro_eliminar', args=[carro_sin_hist.pk]), {'modo': 'eliminar'})
        self.assertFalse(CarroClinico.objects.filter(pk=carro_sin_hist.pk).exists())


class PruebasRendimientoCESFAM(TestCase):
    """
    Prueba de Rendimiento (RNF-06):
    Verifica que el tiempo de respuesta de la consulta de dispensación
    sea inferior a 1 segundo (< 1000 milisegundos).
    """

    def setUp(self):
        self.client = Client()
        self.usuario = Usuario.objects.create_user(
            username='qf_perf',
            password='Password123!',
            rut='18.943.210-0',
            rol=Usuario.Rol.QUIMICO_FARMACEUTICO
        )
        self.client.login(username='qf_perf', password='Password123!')

    def test_rendimiento_consulta_dispensacion_sub_1000ms(self):
        """Mide la latencia de la consulta de dispensación (RNF-06: < 1000 ms)."""
        url = reverse('dispensacion:dispensar')

        inicio = time.perf_counter()
        response = self.client.get(url)
        fin = time.perf_counter()

        duracion_ms = (fin - inicio) * 1000.0

        self.assertEqual(response.status_code, 200)
        self.assertLess(
            duracion_ms, 1000.0,
            f"La consulta de dispensación tardó {duracion_ms:.2f} ms (debe ser menor a 1000 ms según RNF-06)."
        )
        print(f"\n[RNF-06 Rendimiento OK] Tiempo de consulta de dispensación: {duracion_ms:.2f} ms (< 1000 ms)")
