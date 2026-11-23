"""
Modelos del módulo Core del Sistema CESFAM Farmacia.
Contiene: Usuario personalizado con RBAC, Paciente, Médico Prescriptor,
Programas de Salud y configuraciones base.
"""
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


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
        """Solo Químico Farmacéutico y Administrador pueden operar controlados."""
        return self.rol in [self.Rol.ADMINISTRADOR, self.Rol.QUIMICO_FARMACEUTICO]

    def tiene_permiso_dispensacion(self):
        """Químico, Técnico y Admin pueden dispensar."""
        return self.rol in [
            self.Rol.ADMINISTRADOR,
            self.Rol.QUIMICO_FARMACEUTICO,
            self.Rol.TECNICO_FARMACIA,
        ]

    def tiene_permiso_carros(self):
        """Personal clínico y farmacia pueden gestionar carros."""
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
        FONASA_A = 'fonasa_a', 'FONASA Grupo A'
        FONASA_B = 'fonasa_b', 'FONASA Grupo B'
        FONASA_C = 'fonasa_c', 'FONASA Grupo C'
        FONASA_D = 'fonasa_d', 'FONASA Grupo D'
        PRAIS = 'prais', 'PRAIS'

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

    def clean(self):
        from core.utils import validar_rut
        if self.rut and not validar_rut(self.rut):
            raise ValidationError({'rut': 'El RUT ingresado no es válido (Módulo 11).'})


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

