"""
Modelos del módulo Core del Sistema CESFAM Farmacia.
Contiene: Usuario personalizado con RBAC, Paciente, Médico Prescriptor,
Programas de Salud y configuraciones base.
"""
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


class SeccionCurso(models.Model):
    """
    Catálogo de Secciones / Cursos para agrupar funcionarios y estudiantes del simulador.
    """
    nombre = models.CharField(
        max_length=60,
        unique=True,
        verbose_name='Nombre de Sección / Curso',
        help_text='Ej: AP-N4-C1, Sección 001D, Docencia'
    )
    descripcion = models.CharField(
        max_length=180,
        blank=True,
        default='',
        verbose_name='Descripción'
    )
    activa = models.BooleanField(default=True, verbose_name='Activa')
    fecha_creacion = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de creación')

    class Meta:
        verbose_name = 'Sección / Curso'
        verbose_name_plural = 'Secciones / Cursos'
        ordering = ['nombre']
        constraints = [
            models.UniqueConstraint(
                Lower('nombre'),
                name='uniq_seccioncurso_nombre_ci',
            )
        ]

    def clean(self):
        self.nombre = (self.nombre or '').strip()
        if not self.nombre:
            raise ValidationError({'nombre': 'El nombre de la sección no puede estar vacío.'})
        if SeccionCurso.objects.exclude(pk=self.pk).filter(nombre__iexact=self.nombre).exists():
            raise ValidationError({'nombre': f'Ya existe una sección registrada con el nombre "{self.nombre}".'})

    def __str__(self):
        return self.nombre


class Usuario(AbstractUser):
    """
    Modelo de usuario personalizado con Control de Acceso Basado en Roles (RBAC).
    Roles: Administrador, Químico Farmacéutico, Técnico en Farmacia, Personal Clínico.
    """
    class Rol(models.TextChoices):
        ADMINISTRADOR = 'admin', 'Administrador'
        QUIMICO_FARMACEUTICO = 'quimico', 'Químico Farmacéutico'
        TECNICO_FARMACIA = 'tecnico', 'Técnico en Farmacia'
        PERSONAL_CLINICO = 'clinico', 'Personal Clínico (Enfermería)'

    rol = models.CharField(
        max_length=20,
        choices=Rol.choices,
        default=Rol.TECNICO_FARMACIA,
        verbose_name='Rol del usuario'
    )
    rut = models.CharField(
        max_length=12,
        unique=True,
        verbose_name='RUT',
        help_text='Formato: 12.345.678-9'
    )
    telefono = models.CharField(max_length=15, blank=True, verbose_name='Teléfono')
    seccion = models.CharField(
        max_length=60,
        blank=True,
        default='',
        db_index=True,
        verbose_name='Sección / Curso',
        help_text='Ej: AP-N4-C1, Sección 001D, Docencia'
    )
    totp_secret = models.CharField(
        max_length=64,
        blank=True,
        null=True,
        verbose_name='Secreto TOTP (2FA)',
        help_text='Clave secreta para autenticación de segundo factor'
    )
    pin_seguridad = models.CharField(
        max_length=128,
        blank=True,
        null=True,
        verbose_name='PIN de seguridad (hash)',
        help_text='PIN cifrado para operaciones con controlados'
    )
    activo_sistema = models.BooleanField(default=True, verbose_name='Activo en el sistema')
    fecha_creacion = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de creación')
    fecha_modificacion = models.DateTimeField(auto_now=True, verbose_name='Última modificación')

    class Meta:
        verbose_name = 'Usuario'
        verbose_name_plural = 'Usuarios'
        ordering = ['last_name', 'first_name']

    def __str__(self):
        return f'{self.get_full_name()} ({self.get_rol_display()})'

    def tiene_permiso_controlados(self):
        """Solo el Químico Farmacéutico tiene atribución legal para operar y firmar el Libro de Controlados."""
        return self.rol == self.Rol.QUIMICO_FARMACEUTICO

    def tiene_permiso_dispensacion(self):
        """Solo el Químico Farmacéutico y el Técnico en Farmacia pueden dispensar recetas y operar stock."""
        return self.rol in [
            self.Rol.QUIMICO_FARMACEUTICO,
            self.Rol.TECNICO_FARMACIA,
        ]

    def puede_consultar_farmacia(self):
        """Todos los perfiles pueden consultar la disponibilidad de medicamentos en modo lectura."""
        return self.rol in [
            self.Rol.ADMINISTRADOR,
            self.Rol.QUIMICO_FARMACEUTICO,
            self.Rol.TECNICO_FARMACIA,
            self.Rol.PERSONAL_CLINICO,
        ]

    def tiene_permiso_carros(self):
        """Personal clínico y personal de farmacia interactúan con carros clínicos (Admin solo supervisa)."""
        return self.rol in [
            self.Rol.ADMINISTRADOR,
            self.Rol.QUIMICO_FARMACEUTICO,
            self.Rol.TECNICO_FARMACIA,
            self.Rol.PERSONAL_CLINICO,
        ]


class Paciente(models.Model):
    """
    Paciente inscrito en el CESFAM. Datos personales y previsión.
    """
    class Prevision(models.TextChoices):
        FONASA_A = 'fonasa_a', 'FONASA A'
        FONASA_B = 'fonasa_b', 'FONASA B'
        FONASA_C = 'fonasa_c', 'FONASA C'
        FONASA_D = 'fonasa_d', 'FONASA D'
        PRAIS = 'prais', 'PRAIS'
        SIN_PREVISION = 'sin_prevision', 'Sin Previsión'

    rut = models.CharField(max_length=12, unique=True, verbose_name='RUT')
    nombres = models.CharField(max_length=100, verbose_name='Nombres')
    apellido_paterno = models.CharField(max_length=100, verbose_name='Apellido paterno')
    apellido_materno = models.CharField(max_length=100, verbose_name='Apellido materno')
    fecha_nacimiento = models.DateField(verbose_name='Fecha de nacimiento')
    sexo = models.CharField(
        max_length=1,
        choices=[('M', 'Masculino'), ('F', 'Femenino'), ('I', 'Intersex')],
        verbose_name='Sexo'
    )
    direccion = models.CharField(max_length=255, blank=True, verbose_name='Dirección')
    telefono = models.CharField(max_length=15, blank=True, verbose_name='Teléfono')
    email = models.EmailField(blank=True, verbose_name='Correo electrónico')
    prevision = models.CharField(
        max_length=20,
        choices=Prevision.choices,
        default=Prevision.FONASA_A,
        verbose_name='Previsión'
    )
    cronico = models.BooleanField(default=False, verbose_name='Paciente crónico')
    tercero_autorizado_nombre = models.CharField(
        max_length=150,
        blank=True,
        verbose_name='Nombre tercero autorizado'
    )
    tercero_autorizado_rut = models.CharField(
        max_length=12,
        blank=True,
        verbose_name='RUT tercero autorizado'
    )
    tercero_autorizado_parentesco = models.CharField(
        max_length=80,
        blank=True,
        verbose_name='Parentesco / Vínculo tercero'
    )
    activo = models.BooleanField(default=True, verbose_name='Activo')
    fecha_inscripcion = models.DateField(auto_now_add=True, verbose_name='Fecha de inscripción')

    class Meta:
        verbose_name = 'Paciente'
        verbose_name_plural = 'Pacientes'
        ordering = ['apellido_paterno', 'apellido_materno', 'nombres']

    def __str__(self):
        return f'{self.apellido_paterno} {self.apellido_materno}, {self.nombres} ({self.rut})'

    @property
    def nombre_completo(self):
        return f'{self.nombres} {self.apellido_paterno} {self.apellido_materno}'

    @property
    def tiene_tercero_autorizado(self):
        return bool(
            self.tercero_autorizado_nombre
            or self.tercero_autorizado_rut
            or self.tercero_autorizado_parentesco
        )

    def clean(self):
        from core.utils import validar_rut
        if self.rut and not validar_rut(self.rut):
            raise ValidationError({'rut': 'El RUT ingresado no es válido (Módulo 11).'})
        if self.tercero_autorizado_rut and not validar_rut(self.tercero_autorizado_rut):
            raise ValidationError({'tercero_autorizado_rut': 'El RUT del tercero autorizado no es válido (Módulo 11).'})


class MedicoPrescriptor(models.Model):
    """
    Médico habilitado para prescribir recetas en el CESFAM.
    """
    rut = models.CharField(max_length=12, unique=True, verbose_name='RUT')
    nombres = models.CharField(max_length=100, verbose_name='Nombres')
    apellido_paterno = models.CharField(max_length=100, verbose_name='Apellido paterno')
    apellido_materno = models.CharField(max_length=100, verbose_name='Apellido materno')
    especialidad = models.CharField(max_length=100, blank=True, verbose_name='Especialidad')
    registro_sis = models.CharField(
        max_length=20,
        unique=True,
        verbose_name='Registro SIS (Superintendencia)',
        help_text='Número de registro en la Superintendencia de Salud'
    )
    habilitado = models.BooleanField(default=True, verbose_name='Habilitado para prescribir')
    fecha_registro = models.DateField(auto_now_add=True, verbose_name='Fecha de registro')

    class Meta:
        verbose_name = 'Médico prescriptor'
        verbose_name_plural = 'Médicos prescriptores'
        ordering = ['apellido_paterno', 'apellido_materno']

    def __str__(self):
        return f'Dr(a). {self.apellido_paterno} {self.apellido_materno}, {self.nombres} (SIS: {self.registro_sis})'

    def clean(self):
        from core.utils import validar_rut
        if self.rut and not validar_rut(self.rut):
            raise ValidationError({'rut': 'El RUT del médico no es válido.'})


class AuditoriaInmutable(models.Model):
    """
    Bitácora forense bajo patrón append-only almacenada en PostgreSQL (JSONB).
    Cumple con RNF-04, RF-17 y Ley N° 21.719.
    """
    timestamp = models.DateTimeField(default=timezone.now, verbose_name='Estampa de tiempo', db_index=True)
    ip_origen = models.CharField(max_length=45, default='127.0.0.1', verbose_name='IP de origen')
    usuario = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registros_auditoria',
        verbose_name='Usuario'
    )
    usuario_username = models.CharField(max_length=150, verbose_name='Nombre de usuario')
    rol = models.CharField(max_length=50, verbose_name='Rol activo')
    accion = models.CharField(max_length=255, verbose_name='Acción ejecutada')
    entidad_afectada = models.CharField(max_length=255, verbose_name='Entidad afectada')
    valores_anteriores = models.JSONField(default=dict, blank=True, verbose_name='Valores anteriores (JSONB)')
    valores_nuevos = models.JSONField(default=dict, blank=True, verbose_name='Valores nuevos (JSONB)')

    class Meta:
        verbose_name = 'Auditoría Inmutable'
        verbose_name_plural = 'Bitácora de Auditoría Inmutable'
        ordering = ['-timestamp']

    def __str__(self):
        return f'[{self.timestamp.strftime("%d/%m/%Y %H:%M")}] {self.usuario_username}: {self.accion}'


class AlertaSistema(models.Model):
    """
    Alertas automáticas de vencimiento próximo (30/60/90 días) y quiebres de stock en PostgreSQL.
    Cumple con RF-06 y RF-07.
    """
    timestamp = models.DateTimeField(default=timezone.now, verbose_name='Fecha alerta')
    tipo = models.CharField(max_length=50, verbose_name='Tipo de alerta')
    nivel = models.CharField(max_length=30, default='CRITICO', verbose_name='Nivel de criticidad')
    medicamento = models.CharField(max_length=200, verbose_name='Medicamento')
    lote = models.CharField(max_length=50, blank=True, verbose_name='Lote')
    dias_restantes = models.IntegerField(null=True, blank=True, verbose_name='Días restantes')
    ubicacion = models.CharField(max_length=100, blank=True, verbose_name='Ubicación')
    mensaje = models.TextField(blank=True, verbose_name='Mensaje')
    leida = models.BooleanField(default=False, verbose_name='Leída')

    class Meta:
        verbose_name = 'Alerta del Sistema'
        verbose_name_plural = 'Alertas del Sistema'
        ordering = ['-timestamp']

    def __str__(self):
        return f'[{self.nivel}] {self.medicamento} ({self.tipo})'


class EscenarioSimulacion(models.Model):
    """
    Escenario de simulación docente (evaluaciones o talleres) que agrupa
    pacientes y recetas sin alterar el inventario, lotes ni carros clínicos.
    Solo puede existir un escenario activo a la vez.
    """
    class Modalidad(models.TextChoices):
        LIBRE = 'LIBRE', 'Práctica Libre / Juego de Roles'
        INCIDENCIAS = 'INCIDENCIAS', 'Con Incidencias Programadas'

    nombre = models.CharField(
        max_length=150,
        unique=True,
        verbose_name='Nombre del escenario'
    )
    descripcion = models.TextField(
        blank=True,
        verbose_name='Descripción'
    )
    modalidad = models.CharField(
        max_length=20,
        choices=Modalidad.choices,
        default=Modalidad.LIBRE,
        verbose_name='Modalidad del escenario'
    )
    consignas_personalizadas = models.TextField(
        blank=True,
        verbose_name='Incidencias / Consignas personalizadas del docente'
    )
    mostrar_consigna_a_estudiantes = models.BooleanField(
        default=True,
        verbose_name='Mostrar consigna en el Dashboard de los estudiantes'
    )
    activo = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name='Escenario activo'
    )
    pacientes = models.ManyToManyField(
        'core.Paciente',
        blank=True,
        related_name='escenarios',
        verbose_name='Pacientes del escenario'
    )
    recetas = models.ManyToManyField(
        'dispensacion.Receta',
        blank=True,
        related_name='escenarios',
        verbose_name='Recetas del escenario'
    )
    creado_por = models.ForeignKey(
        Usuario,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='escenarios_creados',
        verbose_name='Creado por'
    )
    fecha_creacion = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Fecha de creación'
    )
    actualizado_en = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        verbose_name='Última actualización'
    )
    simular_quiebre = models.BooleanField(
        default=False,
        verbose_name='Simular quiebre de stock'
    )
    medicamento_quiebre = models.ForeignKey(
        'farmacia.Medicamento',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='escenarios_quiebre',
        verbose_name='Fármaco con quiebre simulado'
    )
    simular_alerta_fefo = models.BooleanField(
        default=False,
        verbose_name='Simular alerta FEFO / lote crítico'
    )
    simular_consumo_carro = models.BooleanField(
        default=False,
        verbose_name='Simular consumo en Carro de Paro'
    )

    class Meta:
        verbose_name = 'Escenario de Simulación'
        verbose_name_plural = 'Escenarios de Simulación'
        ordering = ['-activo', '-fecha_creacion', 'nombre']

    def __str__(self):
        estado = 'Activo' if self.activo else 'Inactivo'
        return f'{self.nombre} ({estado})'

    @classmethod
    def obtener_activo(cls):
        """Retorna el escenario activo actual o None si no hay ninguno activo."""
        return cls.objects.filter(activo=True).first()

    def marcar_actualizado(self):
        """Actualiza la marca temporal de versión para disparar refresco en sesiones conectadas."""
        self.actualizado_en = timezone.now()
        self.save(update_fields=['actualizado_en'])

    def activar(self):
        """Activa este escenario desactivando cualquier otro en forma atómica y actualiza versión."""
        from django.db import transaction
        with transaction.atomic():
            EscenarioSimulacion.objects.exclude(pk=self.pk).filter(activo=True).update(activo=False)
            self.activo = True
            self.actualizado_en = timezone.now()
            self.save(update_fields=['activo', 'actualizado_en'])

    def aplicar_incidencias(self, usuario):
        """
        Aplica las incidencias clínicas/logísticas configuradas en este escenario al activarlo
        (únicamente cuando modalidad == INCIDENCIAS):
        - Quiebre de stock (bajo stock mínimo ministerial) del fármaco seleccionado
        - Alerta FEFO (lote crítico a 12 días) + lote vencido en Vitrina (para baja a cuarentena)
        - Consumo de emergencia en el Carro de Paro (2 ampollas de Adrenalina por Personal Clínico)
        """
        if self.modalidad != self.Modalidad.INCIDENCIAS:
            return []

        from datetime import date, timedelta
        from farmacia.models import Medicamento, Ubicacion, Lote, MovimientoStock
        from carros_clinicos.models import CarroClinico, ConsumoCarroClinico

        resumen = []
        hoy = date.today()
        vitrina = Ubicacion.objects.filter(tipo=Ubicacion.TipoUbicacion.VITRINA, activa=True).first()

        # 1. Simular quiebre de stock (bajo stock mínimo ministerial)
        if self.simular_quiebre and self.medicamento_quiebre_id:
            med = self.medicamento_quiebre
            objetivo = max(1, min(5, med.stock_minimo - 1)) if med.stock_minimo > 1 else 0
            lotes_vitrina = list(
                Lote.objects.filter(
                    medicamento=med,
                    activo=True,
                    en_cuarentena=False,
                    fecha_vencimiento__gt=hoy,
                    ubicacion__tipo=Ubicacion.TipoUbicacion.VITRINA,
                ).order_by('fecha_vencimiento')
            )
            if lotes_vitrina:
                for idx, lote in enumerate(lotes_vitrina):
                    nuevo_val = objetivo if idx == 0 else 0
                    if lote.cantidad_actual != nuevo_val:
                        anterior_val = lote.cantidad_actual
                        diff = abs(anterior_val - nuevo_val)
                        lote.cantidad_actual = nuevo_val
                        lote.save(update_fields=['cantidad_actual'])
                        if diff > 0:
                            MovimientoStock.objects.create(
                                lote=lote,
                                tipo=MovimientoStock.TipoMovimiento.AJUSTE,
                                cantidad=diff,
                                cantidad_anterior=anterior_val,
                                cantidad_posterior=nuevo_val,
                                ubicacion_origen=lote.ubicacion,
                                usuario=usuario,
                                motivo=f'Incidencia simulada (Quiebre de stock en vitrina) — Escenario: {self.nombre}',
                            )
            elif vitrina:
                Lote.objects.create(
                    medicamento=med,
                    numero_lote=f'SIM-QUIEBRE-{self.pk}',
                    fecha_fabricacion=hoy - timedelta(days=30),
                    fecha_vencimiento=hoy + timedelta(days=180),
                    cantidad_inicial=max(objetivo, 1),
                    cantidad_actual=objetivo,
                    ubicacion=vitrina,
                    proveedor='Simulación Docente CESFAM',
                )

            # Si aún existe stock en Bodega que impide entrar en quiebre real, ajustarlo para disparar alerta CENABAST
            if med.stock_total >= med.stock_minimo:
                lotes_bodega = Lote.objects.filter(
                    medicamento=med,
                    activo=True,
                    en_cuarentena=False,
                    fecha_vencimiento__gt=hoy,
                    ubicacion__tipo=Ubicacion.TipoUbicacion.BODEGA,
                    cantidad_actual__gt=0,
                ).order_by('fecha_vencimiento')
                for lote_b in lotes_bodega:
                    anterior_val = lote_b.cantidad_actual
                    lote_b.cantidad_actual = 0
                    lote_b.save(update_fields=['cantidad_actual'])
                    MovimientoStock.objects.create(
                        lote=lote_b,
                        tipo=MovimientoStock.TipoMovimiento.AJUSTE,
                        cantidad=anterior_val,
                        cantidad_anterior=anterior_val,
                        cantidad_posterior=0,
                        ubicacion_origen=lote_b.ubicacion,
                        usuario=usuario,
                        motivo=f'Incidencia simulada (Quiebre total de stock para pedido CENABAST) — Escenario: {self.nombre}',
                    )

            AlertaSistema.objects.create(
                tipo='quiebre_stock',
                nivel='CRITICO',
                medicamento=f'{med.nombre_generico} {med.concentracion}',
                ubicacion=vitrina.nombre if vitrina else 'Vitrina de Dispensación',
                mensaje=f'Quiebre simulado por escenario "{self.nombre}": stock disponible reducido a {med.stock_total} (mínimo: {med.stock_minimo}).',
            )
            resumen.append(f'Quiebre de stock de {med.nombre_generico} (stock: {med.stock_total}/{med.stock_minimo})')

        # 2. Simular alerta FEFO (lote crítico a 12 días) + lote vencido en Vitrina para Baja a Cuarentena
        if self.simular_alerta_fefo and vitrina:
            qs_no_ctrl = Medicamento.objects.filter(activo=True, es_controlado=False)
            if self.simular_quiebre and self.medicamento_quiebre_id:
                qs_distinto = qs_no_ctrl.exclude(pk=self.medicamento_quiebre_id)
                med_fefo = (
                    qs_distinto.filter(requiere_receta=True).order_by('id').first()
                    or qs_distinto.order_by('id').first()
                    or self.medicamento_quiebre
                )
            else:
                med_fefo = (
                    self.medicamento_quiebre
                    or qs_no_ctrl.filter(requiere_receta=True).order_by('id').first()
                    or qs_no_ctrl.order_by('id').first()
                    or Medicamento.objects.filter(activo=True).order_by('id').first()
                )
            if med_fefo:
                venc_critico = hoy + timedelta(days=12)
                num_lote = f'SIM-FEFO-{self.pk}'
                lote_crit, _ = Lote.objects.update_or_create(
                    medicamento=med_fefo,
                    numero_lote=num_lote,
                    defaults={
                        'fecha_fabricacion': hoy - timedelta(days=180),
                        'fecha_vencimiento': venc_critico,
                        'cantidad_inicial': 20,
                        'cantidad_actual': 15,
                        'ubicacion': vitrina,
                        'proveedor': 'Simulación Docente FEFO',
                        'activo': True,
                        'en_cuarentena': False,
                        'motivo_cuarentena': '',
                    },
                )
                AlertaSistema.objects.create(
                    tipo='vencimiento_critico',
                    nivel='CRITICO',
                    medicamento=f'{med_fefo.nombre_generico} {med_fefo.concentracion}',
                    lote=lote_crit.numero_lote,
                    dias_restantes=12,
                    ubicacion=vitrina.nombre,
                    mensaje=f'Lote crítico simulado ({lote_crit.numero_lote}) vence en 12 días — Escenario "{self.nombre}".',
                )
                resumen.append(f'Lote crítico FEFO {lote_crit.numero_lote} ({med_fefo.nombre_generico}, vence en 12 días)')

                # Lote vencido en Vitrina para demostrar bloqueo FEFO y Baja a Cuarentena por Q.F.
                num_lote_venc = f'SIM-VENC-{self.pk}'
                lote_venc, _ = Lote.objects.update_or_create(
                    medicamento=med_fefo,
                    numero_lote=num_lote_venc,
                    defaults={
                        'fecha_fabricacion': hoy - timedelta(days=365),
                        'fecha_vencimiento': hoy - timedelta(days=7),
                        'cantidad_inicial': 10,
                        'cantidad_actual': 10,
                        'ubicacion': vitrina,
                        'proveedor': 'Simulación Docente — Pendiente Baja a Cuarentena',
                        'activo': True,
                        'en_cuarentena': False,
                        'motivo_cuarentena': '',
                    },
                )
                AlertaSistema.objects.create(
                    tipo='lote_vencido',
                    nivel='CRITICO',
                    medicamento=f'{med_fefo.nombre_generico} {med_fefo.concentracion}',
                    lote=lote_venc.numero_lote,
                    dias_restantes=-7,
                    ubicacion=vitrina.nombre,
                    mensaje=f'Lote vencido en vitrina ({lote_venc.numero_lote}, vencido hace 7 días) pendiente de baja a cuarentena — Escenario "{self.nombre}".',
                )
                resumen.append(f'Lote vencido en vitrina {lote_venc.numero_lote} ({med_fefo.nombre_generico}, pendiente cuarentena)')

        # 3. Simular consumo de emergencia en Carro de Paro (2 ampollas de Adrenalina por Personal Clínico)
        if self.simular_consumo_carro:
            carro = (
                CarroClinico.objects.filter(activo=True, tipo=CarroClinico.TipoCarro.PARO).first()
                or CarroClinico.objects.filter(activo=True).first()
            )
            if carro:
                item = (
                    carro.plantilla_items.filter(
                        medicamento__nombre_generico__icontains='Adrenalina',
                        cantidad_requerida__gt=0,
                    ).select_related('medicamento').first()
                    or carro.plantilla_items.filter(cantidad_requerida__gt=0).select_related('medicamento').first()
                )
                if item:
                    consumir = min(2, item.cantidad_requerida)
                    item.cantidad_actual = max(0, item.cantidad_requerida - consumir)
                    item.save(update_fields=['cantidad_actual'])
                    carro.estado = CarroClinico.EstadoCarro.INCOMPLETO
                    carro.numero_precinto = ''
                    carro.save(update_fields=['estado', 'numero_precinto'])
                    clinico = (
                        Usuario.objects.filter(rol=Usuario.Rol.PERSONAL_CLINICO, is_active=True).order_by('id').first()
                        or usuario
                    )
                    ConsumoCarroClinico.objects.create(
                        carro=carro,
                        item=item,
                        cantidad_consumida=consumir,
                        motivo=f'Emergencia simulada (Código Azul — Reanimación) — Escenario: {self.nombre}',
                        paciente_atendido='Caso Simulado de Urgencia',
                        personal_clinico=clinico,
                    )
                    resumen.append(
                        f'Consumo en {carro.nombre}: -{consumir} {item.medicamento.nombre_generico} por {clinico.get_full_name() or clinico.username} (Precinto Roto — Pendiente Resellado)'
                    )

        return resumen


