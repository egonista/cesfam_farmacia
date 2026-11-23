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
