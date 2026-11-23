"""
Modelos del módulo GES/AUGE del Sistema CESFAM.
Garantías Explícitas en Salud: patologías, canastas farmacológicas y cuotas.
"""
from django.db import models
from django.core.exceptions import ValidationError


class PatologiaGES(models.Model):
    """Patología incluida en el programa GES/AUGE."""
    codigo = models.CharField(max_length=10, unique=True, verbose_name='Código GES')
    nombre = models.CharField(max_length=200, verbose_name='Nombre de la patología')
    descripcion = models.TextField(blank=True, verbose_name='Descripción')
    activa = models.BooleanField(default=True, verbose_name='Activa')

    class Meta:
        verbose_name = 'Patología GES'
        verbose_name_plural = 'Patologías GES'
        ordering = ['codigo']

    def __str__(self):
        return f'[{self.codigo}] {self.nombre}'


class CanastaGES(models.Model):
    """Canasta farmacológica oficial de una patología GES."""
    patologia = models.ForeignKey(
        PatologiaGES,
        on_delete=models.CASCADE,
        related_name='canastas',
        verbose_name='Patología GES'
    )
    medicamento = models.ForeignKey(
        'farmacia.Medicamento',
        on_delete=models.PROTECT,
        related_name='canastas_ges',
        verbose_name='Medicamento'
    )
    cantidad_por_cuota = models.PositiveIntegerField(
        verbose_name='Cantidad por cuota',
        help_text='Unidades autorizadas por cada cuota de despacho'
    )
    cuotas_autorizadas = models.PositiveIntegerField(
        default=12,
        verbose_name='Cuotas autorizadas (anual)',
        help_text='Número máximo de cuotas anuales'
    )

    class Meta:
        verbose_name = 'Canasta GES'
        verbose_name_plural = 'Canastas GES'
        unique_together = ['patologia', 'medicamento']

    def __str__(self):
        return f'{self.patologia.nombre} - {self.medicamento.nombre_generico} ({self.cantidad_por_cuota}/cuota)'


class InscripcionGES(models.Model):
    """Inscripción de un paciente en una patología GES activa."""
    paciente = models.ForeignKey(
        'core.Paciente',
        on_delete=models.PROTECT,
        related_name='inscripciones_ges',
        verbose_name='Paciente'
    )
    patologia = models.ForeignKey(
        PatologiaGES,
        on_delete=models.PROTECT,
        related_name='inscripciones',
        verbose_name='Patología GES'
    )
    fecha_inscripcion = models.DateField(verbose_name='Fecha de inscripción')
    fecha_inicio_periodo = models.DateField(verbose_name='Inicio período de cuotas')
    fecha_fin_periodo = models.DateField(verbose_name='Fin período de cuotas')
    activa = models.BooleanField(default=True, verbose_name='Inscripción activa')

    class Meta:
        verbose_name = 'Inscripción GES'
        verbose_name_plural = 'Inscripciones GES'
        unique_together = ['paciente', 'patologia']

    def __str__(self):
        return f'{self.paciente.nombre_completo} - {self.patologia.nombre}'


class CuotaGES(models.Model):
    """Control de cuotas entregadas a un paciente por inscripción GES."""
    inscripcion = models.ForeignKey(
        InscripcionGES,
        on_delete=models.PROTECT,
        related_name='cuotas',
        verbose_name='Inscripción GES'
    )
    canasta = models.ForeignKey(
        CanastaGES,
        on_delete=models.PROTECT,
        related_name='cuotas_entregadas',
        verbose_name='Canasta GES'
    )
    numero_cuota = models.PositiveIntegerField(verbose_name='Número de cuota')
    cantidad_entregada = models.PositiveIntegerField(verbose_name='Cantidad entregada')
    dispensacion = models.ForeignKey(
        'dispensacion.Dispensacion',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='cuotas_ges',
        verbose_name='Dispensación asociada'
    )
    fecha_entrega = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de entrega')

    class Meta:
        verbose_name = 'Cuota GES entregada'
        verbose_name_plural = 'Cuotas GES entregadas'
        unique_together = ['inscripcion', 'canasta', 'numero_cuota']
        ordering = ['numero_cuota']

    def __str__(self):
        return f'Cuota {self.numero_cuota}/{self.canasta.cuotas_autorizadas} - {self.canasta.medicamento.nombre_generico}'
