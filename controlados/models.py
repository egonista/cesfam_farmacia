"""
Modelos del módulo de Medicamentos Controlados del Sistema CESFAM.
Libro Oficial Digital de Estupefacientes y Psicotrópicos (D.S. 404/405).
"""
from django.db import models
from django.utils import timezone


class LibroControlados(models.Model):
    """
    Libro Oficial Digital de Medicamentos Controlados.
    Registro foliado de ingresos, egresos y saldos.
    """
    class TipoMovimiento(models.TextChoices):
        INGRESO = 'ingreso', 'Ingreso'
        EGRESO = 'egreso', 'Egreso (Dispensación)'
        MERMA = 'merma', 'Merma / Destrucción'
        DEVOLUCION = 'devolucion', 'Devolución'

    folio = models.PositiveIntegerField(
        unique=True,
        verbose_name='Folio',
        help_text='Número correlativo del registro'
    )
    medicamento = models.ForeignKey(
        'farmacia.Medicamento',
        on_delete=models.PROTECT,
        related_name='registros_controlados',
        verbose_name='Medicamento controlado'
    )
    lote = models.ForeignKey(
        'farmacia.Lote',
        on_delete=models.PROTECT,
        related_name='registros_controlados',
        verbose_name='Lote'
    )
    tipo_movimiento = models.CharField(
        max_length=20,
        choices=TipoMovimiento.choices,
        verbose_name='Tipo de movimiento'
    )
    cantidad = models.PositiveIntegerField(verbose_name='Cantidad')
    saldo_anterior = models.PositiveIntegerField(verbose_name='Saldo anterior')
    saldo_posterior = models.PositiveIntegerField(verbose_name='Saldo posterior')
    receta = models.ForeignKey(
        'dispensacion.Receta',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='registros_controlados',
        verbose_name='Receta (si aplica)'
    )
    paciente = models.ForeignKey(
        'core.Paciente',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='registros_controlados',
        verbose_name='Paciente'
    )
    quimico_responsable = models.ForeignKey(
        'core.Usuario',
        on_delete=models.PROTECT,
        related_name='registros_controlados',
        verbose_name='Químico farmacéutico responsable'
    )
    verificacion_2fa = models.BooleanField(
        default=False,
        verbose_name='Verificación 2FA realizada',
        help_text='Indica si se verificó el segundo factor (TOTP/PIN)'
    )
    observaciones = models.TextField(blank=True, verbose_name='Observaciones')
    fecha_registro = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de registro')

    class Meta:
        verbose_name = 'Registro de controlado'
        verbose_name_plural = 'Libro de controlados'
        ordering = ['folio']

    def __str__(self):
        return f'Folio {self.folio} - {self.get_tipo_movimiento_display()} {self.medicamento.nombre_generico} x{self.cantidad}'

    @classmethod
    def siguiente_folio(cls):
        """Retorna el próximo folio disponible."""
        ultimo = cls.objects.order_by('-folio').first()
        return (ultimo.folio + 1) if ultimo else 1
