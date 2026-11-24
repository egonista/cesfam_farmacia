"""
Modelos del módulo Dispensación Asistencial del Sistema CESFAM.
Contiene: Receta, DetalleReceta, Dispensación, TerceroAutorizado.
Implementa lógica de dispensación gratuita ($0 copago) y retiro por tercero.
"""
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Receta(models.Model):
    """Receta médica emitida por un prescriptor habilitado del CESFAM."""
    
    class EstadoReceta(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente'
        DISPENSADA_PARCIAL = 'parcial', 'Dispensada Parcialmente'
        DISPENSADA_TOTAL = 'total', 'Dispensada Totalmente'
        ANULADA = 'anulada', 'Anulada'
        VENCIDA = 'vencida', 'Vencida'

    class TipoReceta(models.TextChoices):
        SIMPLE = 'simple', 'Receta Simple'
        RETENIDA = 'retenida', 'Receta Retenida'
        CHEQUE = 'cheque', 'Receta Cheque (Controlados)'
        CRONICA = 'cronica', 'Receta Crónica'

    numero_receta = models.CharField(
        max_length=20,
        unique=True,
        verbose_name='Número de receta'
    )
    paciente = models.ForeignKey(
        'core.Paciente',
        on_delete=models.PROTECT,
        related_name='recetas',
        verbose_name='Paciente'
    )
    medico = models.ForeignKey(
        'core.MedicoPrescriptor',
        on_delete=models.PROTECT,
        related_name='recetas',
        verbose_name='Médico prescriptor'
    )
    tipo = models.CharField(
        max_length=20,
        choices=TipoReceta.choices,
        default=TipoReceta.SIMPLE,
        verbose_name='Tipo de receta'
    )
    estado = models.CharField(
        max_length=20,
        choices=EstadoReceta.choices,
        default=EstadoReceta.PENDIENTE,
        verbose_name='Estado'
    )
    diagnostico = models.TextField(verbose_name='Diagnóstico')
    fecha_emision = models.DateField(verbose_name='Fecha de emisión')
    fecha_vencimiento = models.DateField(verbose_name='Fecha de vencimiento de la receta')
    observaciones = models.TextField(blank=True, verbose_name='Observaciones')
    autorizada_qf = models.BooleanField(
        default=False,
        verbose_name='Autorizada por Químico Farmacéutico',
        help_text='Visto bueno del Q.F. obligatorio para recetas controladas/retenidas antes de despacho por TENS'
    )
    qf_autorizador = models.ForeignKey(
        'core.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recetas_autorizadas_qf',
        verbose_name='Q.F. que autoriza'
    )
    fecha_autorizacion_qf = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha autorización Q.F.'
    )
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Receta'
        verbose_name_plural = 'Recetas'
        ordering = ['-fecha_emision']

    def __str__(self):
        return f'Receta {self.numero_receta} - {self.paciente.nombre_completo}'

    @property
    def esta_vigente(self):
        """
        True si la receta no ha vencido ni está anulada.
        Las recetas simples, retenidas y cheque tienen una vigencia máxima de 30 días desde su emisión.
        Las recetas crónicas respetan su fecha de vencimiento (hasta 180 días).
        """
        from datetime import date
        hoy = date.today()
        if self.estado in (self.EstadoReceta.ANULADA, self.EstadoReceta.VENCIDA):
            return False
        if self.fecha_vencimiento < hoy:
            return False
        dias_desde_emision = (hoy - self.fecha_emision).days
        if self.tipo != self.TipoReceta.CRONICA and dias_desde_emision > 30:
            return False
        return True

    @property
    def esta_vencida(self):
        """True si la receta caducó por fecha de vencimiento, plazo legal de 30 días o estado."""
        from datetime import date
        hoy = date.today()
        if self.estado == self.EstadoReceta.VENCIDA:
            return True
        if self.estado in (self.EstadoReceta.ANULADA, self.EstadoReceta.DISPENSADA_TOTAL):
            return False
        if self.fecha_vencimiento < hoy:
            return True
        if self.tipo != self.TipoReceta.CRONICA and (hoy - self.fecha_emision).days > 30:
            return True
        return False

    @property
    def tiene_medicamento_controlado(self):
        """True si algún detalle prescrito corresponde a un fármaco controlado."""
        return self.detalles.filter(medicamento__es_controlado=True).exists()

    @property
    def es_controlada(self):
        """True si la receta es retenida, cheque o prescribe algún fármaco controlado."""
        return (
            self.tipo in (self.TipoReceta.CHEQUE, self.TipoReceta.RETENIDA)
            or self.tiene_medicamento_controlado
        )

    @property
    def requiere_autorizacion_qf(self):
        """True si es controlada/retenida, está pendiente y aún no tiene visto bueno del Q.F."""
        return self.es_controlada and not self.autorizada_qf and self.estado in (
            self.EstadoReceta.PENDIENTE,
            self.EstadoReceta.DISPENSADA_PARCIAL,
        )


class DetalleReceta(models.Model):
    """Detalle de cada medicamento prescrito en una receta."""
    receta = models.ForeignKey(
        Receta,
        on_delete=models.CASCADE,
        related_name='detalles',
        verbose_name='Receta'
    )
    medicamento = models.ForeignKey(
        'farmacia.Medicamento',
        on_delete=models.PROTECT,
        related_name='detalles_receta',
        verbose_name='Medicamento'
    )
    cantidad_prescrita = models.PositiveIntegerField(verbose_name='Cantidad prescrita')
    cantidad_dispensada = models.PositiveIntegerField(default=0, verbose_name='Cantidad dispensada')
    posologia = models.CharField(max_length=255, verbose_name='Posología')
    dias_tratamiento = models.PositiveIntegerField(
        default=30,
        verbose_name='Días de tratamiento',
        help_text='Número de días que dura el tratamiento'
    )
    observaciones = models.TextField(blank=True, verbose_name='Observaciones')

    class Meta:
        verbose_name = 'Detalle de receta'
        verbose_name_plural = 'Detalles de receta'

    def __str__(self):
        return f'{self.medicamento.nombre_generico} x{self.cantidad_prescrita}'

    @property
    def cantidad_pendiente(self):
        return self.cantidad_prescrita - self.cantidad_dispensada

    @property
    def completamente_dispensado(self):
        return self.cantidad_dispensada >= self.cantidad_prescrita


class TerceroAutorizado(models.Model):
    """Tercero autorizado para retirar medicamentos en nombre del paciente."""
    rut = models.CharField(max_length=12, verbose_name='RUT del tercero')
    nombres = models.CharField(max_length=100, verbose_name='Nombres')
    apellido_paterno = models.CharField(max_length=100, verbose_name='Apellido paterno')
    apellido_materno = models.CharField(max_length=100, blank=True, verbose_name='Apellido materno')
    parentesco = models.CharField(max_length=50, verbose_name='Parentesco con el paciente')
    telefono = models.CharField(max_length=15, verbose_name='Teléfono de contacto')

    class Meta:
        verbose_name = 'Tercero autorizado'
        verbose_name_plural = 'Terceros autorizados'

    def __str__(self):
        return f'{self.nombres} {self.apellido_paterno} (RUT: {self.rut})'

    @property
    def nombre_completo(self):
        return f'{self.nombres} {self.apellido_paterno} {self.apellido_materno}'.strip()

    def clean(self):
        from core.utils import validar_rut
        if self.rut and not validar_rut(self.rut):
            raise ValidationError({'rut': 'El RUT del tercero autorizado no es válido.'})


class Dispensacion(models.Model):
    """
    Registro de una dispensación de medicamentos.
    Vincula la receta con los lotes despachados y opcionalmente un tercero autorizado.
    Siempre $0 copago (dispensación gratuita APS).
    """
    receta = models.ForeignKey(
        Receta,
        on_delete=models.PROTECT,
        related_name='dispensaciones',
        verbose_name='Receta'
    )
    usuario_dispensador = models.ForeignKey(
        'core.Usuario',
        on_delete=models.PROTECT,
        related_name='dispensaciones',
        verbose_name='Dispensado por'
    )
    retiro_tercero = models.BooleanField(
        default=False,
        verbose_name='Retiro por tercero autorizado'
    )
    tercero_autorizado = models.ForeignKey(
        TerceroAutorizado,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='dispensaciones',
        verbose_name='Tercero autorizado'
    )
    copago = models.DecimalField(
        max_digits=10,
        decimal_places=0,
        default=0,
        verbose_name='Copago',
        help_text='Siempre $0 en APS'
    )
    observaciones = models.TextField(blank=True, verbose_name='Observaciones')
    fecha = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de dispensación')

    class Meta:
        verbose_name = 'Dispensación'
        verbose_name_plural = 'Dispensaciones'
        ordering = ['-fecha']

    def __str__(self):
        return f'Disp. #{self.id} - Receta {self.receta.numero_receta} ({self.fecha.strftime("%d/%m/%Y")})'

    def clean(self):
        if self.retiro_tercero and not self.tercero_autorizado:
            raise ValidationError(
                'Si el retiro es por tercero autorizado, debe especificar los datos del tercero.'
            )


class DetalleDispensacion(models.Model):
    """Detalle de cada medicamento y lote dispensado."""
    dispensacion = models.ForeignKey(
        Dispensacion,
        on_delete=models.CASCADE,
        related_name='detalles',
        verbose_name='Dispensación'
    )
    detalle_receta = models.ForeignKey(
        DetalleReceta,
        on_delete=models.PROTECT,
        related_name='dispensaciones',
        verbose_name='Detalle de receta'
    )
    lote = models.ForeignKey(
        'farmacia.Lote',
        on_delete=models.PROTECT,
        related_name='dispensaciones',
        verbose_name='Lote dispensado'
    )
    cantidad = models.PositiveIntegerField(verbose_name='Cantidad dispensada')
    fefo_override = models.BooleanField(
        default=False,
        verbose_name='Override FEFO',
        help_text='True si el QF forzó un lote distinto al sugerido por FEFO'
    )
    justificacion_override = models.TextField(
        blank=True,
        verbose_name='Justificación técnica (override FEFO)',
        help_text='Obligatoria si se omitió el lote FEFO sugerido'
    )
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Detalle de dispensación'
        verbose_name_plural = 'Detalles de dispensación'

    def __str__(self):
        return f'{self.detalle_receta.medicamento.nombre_generico} x{self.cantidad} (Lote: {self.lote.numero_lote})'

    def clean(self):
        if self.fefo_override and not self.justificacion_override:
            raise ValidationError(
                'Se requiere justificación técnica obligatoria al forzar un lote distinto al FEFO.'
            )
