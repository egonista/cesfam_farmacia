"""
Modelos del módulo Carros Clínicos del Sistema CESFAM.
Gestión de Carros de Paro y Unidosis.
"""
from django.db import models
from django.utils import timezone


class CarroClinico(models.Model):
    """Carro clínico (Paro o Unidosis) del CESFAM."""
    
    class TipoCarro(models.TextChoices):
        PARO = 'paro', 'Carro de Paro'
        UNIDOSIS = 'unidosis', 'Carro de Unidosis'

    class EstadoCarro(models.TextChoices):
        COMPLETO = 'completo', 'Completo - Operativo'
        INCOMPLETO = 'incompleto', 'Incompleto - En Reposición'
        EN_USO = 'en_uso', 'En Uso (Emergencia)'
        MANTENIMIENTO = 'mantenimiento', 'En Mantenimiento'

    nombre = models.CharField(max_length=100, verbose_name='Nombre del carro')
    tipo = models.CharField(
        max_length=20,
        choices=TipoCarro.choices,
        verbose_name='Tipo de carro'
    )
    ubicacion_fisica = models.CharField(
        max_length=200,
        verbose_name='Ubicación física',
        help_text='Ej: Box de Reanimación, Sala de Procedimientos'
    )
    estado = models.CharField(
        max_length=20,
        choices=EstadoCarro.choices,
        default=EstadoCarro.COMPLETO,
        verbose_name='Estado actual'
    )
    numero_precinto = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='Número de precinto de seguridad'
    )
    fecha_ultimo_precinto = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Fecha último precintado'
    )
    responsable_actual = models.ForeignKey(
        'core.Usuario',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='carros_responsable',
        verbose_name='Responsable actual'
    )
    activo = models.BooleanField(default=True, verbose_name='Activo')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Carro clínico'
        verbose_name_plural = 'Carros clínicos'
        ordering = ['tipo', 'nombre']

    def __str__(self):
        return f'{self.nombre} ({self.get_tipo_display()}) - {self.get_estado_display()}'

    @property
    def esta_completo(self):
        """Verifica si todos los ítems de la plantilla están completos."""
        for item in self.plantilla_items.all():
            if item.cantidad_actual < item.cantidad_requerida:
                return False
        return True


class PlantillaItemCarro(models.Model):
    """Plantilla canónica: qué medicamentos y cantidades debe tener el carro."""
    carro = models.ForeignKey(
        CarroClinico,
        on_delete=models.CASCADE,
        related_name='plantilla_items',
        verbose_name='Carro clínico'
    )
    medicamento = models.ForeignKey(
        'farmacia.Medicamento',
        on_delete=models.PROTECT,
        related_name='items_carro',
        verbose_name='Medicamento'
    )
    cantidad_requerida = models.PositiveIntegerField(
        verbose_name='Cantidad requerida',
        help_text='Cantidad que debe tener el carro según protocolo'
    )
    cantidad_actual = models.PositiveIntegerField(
        default=0,
        verbose_name='Cantidad actual'
    )
    ubicacion_en_carro = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='Ubicación en el carro',
        help_text='Ej: Cajón 1, Bandeja Superior'
    )

    class Meta:
        verbose_name = 'Item de plantilla de carro'
        verbose_name_plural = 'Items de plantilla de carro'
        unique_together = ['carro', 'medicamento']

    def __str__(self):
        return f'{self.medicamento.nombre_generico} ({self.cantidad_actual}/{self.cantidad_requerida})'

    @property
    def esta_completo(self):
        return self.cantidad_actual >= self.cantidad_requerida

    @property
    def faltante(self):
        return max(0, self.cantidad_requerida - self.cantidad_actual)


class ConsumoCarroClinico(models.Model):
    """Registro de consumo de medicamentos del carro durante una emergencia."""
    carro = models.ForeignKey(
        CarroClinico,
        on_delete=models.PROTECT,
        related_name='consumos',
        verbose_name='Carro clínico'
    )
    item = models.ForeignKey(
        PlantillaItemCarro,
        on_delete=models.PROTECT,
        related_name='consumos',
        verbose_name='Item del carro'
    )
    cantidad_consumida = models.PositiveIntegerField(verbose_name='Cantidad consumida')
    motivo = models.TextField(
        verbose_name='Motivo del consumo',
        help_text='Describir la emergencia o situación clínica'
    )
    paciente_atendido = models.CharField(
        max_length=200,
        blank=True,
        verbose_name='Paciente atendido (referencia)'
    )
    personal_clinico = models.ForeignKey(
        'core.Usuario',
        on_delete=models.PROTECT,
        related_name='consumos_carro',
        verbose_name='Personal clínico que registra'
    )
    fecha = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de consumo')

    class Meta:
        verbose_name = 'Consumo de carro clínico'
        verbose_name_plural = 'Consumos de carros clínicos'
        ordering = ['-fecha']

    def __str__(self):
        return f'Consumo en {self.carro.nombre} - {self.item.medicamento.nombre_generico} x{self.cantidad_consumida}'


class ReposicionCarro(models.Model):
    """Registro de reposición del carro clínico desde farmacia."""
    carro = models.ForeignKey(
        CarroClinico,
        on_delete=models.PROTECT,
        related_name='reposiciones',
        verbose_name='Carro clínico'
    )
    item = models.ForeignKey(
        PlantillaItemCarro,
        on_delete=models.PROTECT,
        related_name='reposiciones',
        verbose_name='Item repuesto'
    )
    lote = models.ForeignKey(
        'farmacia.Lote',
        on_delete=models.PROTECT,
        related_name='reposiciones_carro',
        verbose_name='Lote utilizado'
    )
    cantidad_repuesta = models.PositiveIntegerField(verbose_name='Cantidad repuesta')
    usuario_farmacia = models.ForeignKey(
        'core.Usuario',
        on_delete=models.PROTECT,
        related_name='reposiciones_carro',
        verbose_name='Responsable de farmacia'
    )
    nuevo_precinto = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='Número de nuevo precinto'
    )
    fecha = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de reposición')

    class Meta:
        verbose_name = 'Reposición de carro'
        verbose_name_plural = 'Reposiciones de carro'
        ordering = ['-fecha']

    def __str__(self):
        return f'Reposición {self.carro.nombre} - {self.item.medicamento.nombre_generico} x{self.cantidad_repuesta}'
