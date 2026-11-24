"""
Modelos del módulo Farmacia del Sistema CESFAM.
Contiene: Categorías, Medicamentos, Lotes (con FEFO), Ubicaciones y Movimientos de Stock.
"""
from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class CategoriaMedicamento(models.Model):
    """Categoría o clasificación farmacológica del medicamento."""
    nombre = models.CharField(max_length=100, unique=True, verbose_name='Nombre')
    descripcion = models.TextField(blank=True, verbose_name='Descripción')
    es_controlado = models.BooleanField(
        default=False,
        verbose_name='Es controlado (D.S. 404/405)',
        help_text='Indica si los medicamentos de esta categoría son estupefacientes o psicotrópicos'
    )

    class Meta:
        verbose_name = 'Categoría de medicamento'
        verbose_name_plural = 'Categorías de medicamentos'
        ordering = ['nombre']

    def __str__(self):
        sufijo = ' ⚠️ CONTROLADO' if self.es_controlado else ''
        return f'{self.nombre}{sufijo}'


class Medicamento(models.Model):
    """Medicamento registrado en el arsenal farmacológico del CESFAM."""
    
    class UnidadMedida(models.TextChoices):
        COMPRIMIDO = 'comp', 'Comprimido'
        CAPSULA = 'cap', 'Cápsula'
        AMPOLLA = 'amp', 'Ampolla'
        FRASCO = 'frasco', 'Frasco'
        SOBRE = 'sobre', 'Sobre'
        TUBO = 'tubo', 'Tubo'
        INHALADOR = 'inhalador', 'Inhalador'
        ML = 'ml', 'Mililitro (ml)'
        MG = 'mg', 'Miligramo (mg)'
        UNIDAD = 'unidad', 'Unidad'

    codigo = models.CharField(
        max_length=20,
        unique=True,
        verbose_name='Código interno',
        help_text='Código alfanumérico único del medicamento'
    )
    nombre_generico = models.CharField(max_length=200, verbose_name='Nombre genérico (DCI)')
    nombre_comercial = models.CharField(max_length=200, blank=True, verbose_name='Nombre comercial')
    concentracion = models.CharField(max_length=50, verbose_name='Concentración')
    forma_farmaceutica = models.CharField(max_length=100, verbose_name='Forma farmacéutica')
    unidad_medida = models.CharField(
        max_length=20,
        choices=UnidadMedida.choices,
        default=UnidadMedida.COMPRIMIDO,
        verbose_name='Unidad de medida'
    )
    categoria = models.ForeignKey(
        CategoriaMedicamento,
        on_delete=models.PROTECT,
        related_name='medicamentos',
        verbose_name='Categoría'
    )
    stock_minimo = models.PositiveIntegerField(
        default=10,
        verbose_name='Stock mínimo (alerta)',
        help_text='Cantidad mínima antes de generar alerta de quiebre'
    )
    stock_maximo = models.PositiveIntegerField(
        default=1000,
        verbose_name='Stock máximo'
    )
    requiere_receta = models.BooleanField(default=True, verbose_name='Requiere receta')
    es_controlado = models.BooleanField(
        default=False,
        verbose_name='Es controlado',
        help_text='Requiere registro en Libro de Controlados (D.S. 404/405)'
    )
    activo = models.BooleanField(default=True, verbose_name='Activo en arsenal')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_modificacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Medicamento'
        verbose_name_plural = 'Medicamentos'
        ordering = ['nombre_generico']

    def __str__(self):
        ctrl = ' [CONTROLADO]' if self.es_controlado else ''
        return f'{self.nombre_generico} {self.concentracion} ({self.forma_farmaceutica}){ctrl}'

    def _stock_vigente(self, tipo_ubicacion=None):
        """Suma el stock actual de lotes activos, fuera de cuarentena y vigentes, filtrable por ubicación."""
        qs = self.lotes.filter(activo=True, en_cuarentena=False).select_related('ubicacion')
        if tipo_ubicacion:
            qs = qs.filter(ubicacion__tipo=tipo_ubicacion)
        return sum(lote.cantidad_actual for lote in qs if not lote.esta_vencido)

    @property
    def stock_total(self):
        """Stock total sumando todos los lotes vigentes y activos (excluye cuarentena)."""
        return self._stock_vigente()

    @property
    def stock_vitrina(self):
        """Stock vigente ubicado en Vitrina de Dispensación."""
        return self._stock_vigente(Ubicacion.TipoUbicacion.VITRINA)

    @property
    def stock_bodega(self):
        """Stock vigente ubicado en Bodega Central."""
        return self._stock_vigente(Ubicacion.TipoUbicacion.BODEGA)

    @property
    def unidad_medida_plural(self):
        """Retorna la etiqueta plural legible de la unidad de medida para formularios."""
        plurales = {
            self.UnidadMedida.COMPRIMIDO: 'Comprimidos',
            self.UnidadMedida.CAPSULA: 'Cápsulas',
            self.UnidadMedida.AMPOLLA: 'Ampollas',
            self.UnidadMedida.FRASCO: 'Frascos',
            self.UnidadMedida.SOBRE: 'Sobres',
            self.UnidadMedida.TUBO: 'Tubos',
            self.UnidadMedida.INHALADOR: 'Inhaladores',
            self.UnidadMedida.ML: 'ml',
            self.UnidadMedida.MG: 'mg',
            self.UnidadMedida.UNIDAD: 'Unidades',
        }
        return plurales.get(self.unidad_medida, self.get_unidad_medida_display())

    @property
    def en_quiebre(self):
        """True si el stock total está por debajo del mínimo."""
        return self.stock_total < self.stock_minimo

    def lotes_fefo(self, ubicacion=None):
        """
        Retorna los lotes ordenados por FEFO (First Expired, First Out).
        Solo incluye lotes con stock > 0, no vencidos, no en cuarentena y activos.
        """
        qs = self.lotes.filter(
            activo=True,
            en_cuarentena=False,
            cantidad_actual__gt=0,
            fecha_vencimiento__gt=date.today(),
        )
        if ubicacion:
            qs = qs.filter(ubicacion=ubicacion)
        return qs.order_by('fecha_vencimiento')


class Ubicacion(models.Model):
    """Ubicación física del stock: Bodega Central o Vitrina de Dispensación."""
    
    class TipoUbicacion(models.TextChoices):
        BODEGA = 'bodega', 'Bodega Central'
        VITRINA = 'vitrina', 'Vitrina de Dispensación'

    nombre = models.CharField(max_length=100, verbose_name='Nombre')
    tipo = models.CharField(
        max_length=20,
        choices=TipoUbicacion.choices,
        verbose_name='Tipo de ubicación'
    )
    descripcion = models.TextField(blank=True, verbose_name='Descripción')
    activa = models.BooleanField(default=True, verbose_name='Activa')

    class Meta:
        verbose_name = 'Ubicación'
        verbose_name_plural = 'Ubicaciones'
        ordering = ['tipo', 'nombre']

    def __str__(self):
        return f'{self.nombre} ({self.get_tipo_display()})'


class Lote(models.Model):
    """
    Lote de un medicamento con fecha de vencimiento.
    Unidad fundamental para el algoritmo FEFO.
    """
    medicamento = models.ForeignKey(
        Medicamento,
        on_delete=models.PROTECT,
        related_name='lotes',
        verbose_name='Medicamento'
    )
    numero_lote = models.CharField(max_length=50, verbose_name='Número de lote')
    fecha_fabricacion = models.DateField(verbose_name='Fecha de fabricación')
    fecha_vencimiento = models.DateField(verbose_name='Fecha de vencimiento')
    cantidad_inicial = models.PositiveIntegerField(verbose_name='Cantidad inicial')
    cantidad_actual = models.PositiveIntegerField(verbose_name='Cantidad actual')
    ubicacion = models.ForeignKey(
        Ubicacion,
        on_delete=models.PROTECT,
        related_name='lotes',
        verbose_name='Ubicación'
    )
    proveedor = models.CharField(max_length=200, blank=True, verbose_name='Proveedor / Laboratorio')
    precio_unitario = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0,
        verbose_name='Costo unitario (referencia)',
        help_text='Solo referencial, dispensación es gratuita'
    )
    activo = models.BooleanField(default=True, verbose_name='Lote activo')
    en_cuarentena = models.BooleanField(default=False, verbose_name='En Cuarentena / Baja por Vencimiento')
    motivo_cuarentena = models.TextField(blank=True, verbose_name='Motivo de cuarentena / baja')
    fecha_cuarentena = models.DateTimeField(null=True, blank=True, verbose_name='Fecha de pase a cuarentena')
    usuario_cuarentena = models.ForeignKey(
        'core.Usuario',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='lotes_cuarentena',
        verbose_name='Responsable de baja / cuarentena'
    )
    fecha_registro = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Lote'
        verbose_name_plural = 'Lotes'
        ordering = ['fecha_vencimiento']
        unique_together = ['medicamento', 'numero_lote', 'ubicacion']

    def __str__(self):
        if self.en_cuarentena:
            estado = 'CUARENTENA / BAJA'
        elif self.esta_vencido:
            estado = '⛔ VENCIDO'
        else:
            estado = f'Vence: {self.fecha_vencimiento.strftime("%d/%m/%Y")}'
        return f'Lote {self.numero_lote} - {self.medicamento.nombre_generico} ({estado})'

    @property
    def esta_vencido(self):
        """True si el lote ya venció."""
        return self.fecha_vencimiento <= date.today()

    @property
    def dias_para_vencer(self):
        """Días restantes hasta el vencimiento."""
        return (self.fecha_vencimiento - date.today()).days

    @property
    def alerta_vencimiento(self):
        """Retorna el nivel de alerta de vencimiento o cuarentena."""
        if self.en_cuarentena:
            return 'cuarentena'
        dias = self.dias_para_vencer
        if dias <= 0:
            return 'vencido'
        elif dias <= 30:
            return 'critico'  # 30 días
        elif dias <= 60:
            return 'alto'     # 60 días
        elif dias <= 90:
            return 'medio'    # 90 días
        return 'normal'

    def puede_dispensar(self, dias_tratamiento=0):
        """
        Verifica si el lote puede ser dispensado.
        Un lote no puede dispensarse si:
        - Está en cuarentena o inactivo
        - Está vencido
        - Su vida útil remanente es menor a los días de tratamiento
        - No tiene stock
        """
        if self.en_cuarentena or not self.activo:
            return False
        if self.esta_vencido:
            return False
        if self.cantidad_actual <= 0:
            return False
        if dias_tratamiento > 0 and self.dias_para_vencer < dias_tratamiento:
            return False
        return True

    def clean(self):
        if self.fecha_vencimiento and self.fecha_fabricacion:
            if self.fecha_vencimiento <= self.fecha_fabricacion:
                raise ValidationError('La fecha de vencimiento debe ser posterior a la de fabricación.')


class MovimientoStock(models.Model):
    """Registro de movimientos de stock (ingresos, egresos, traspasos)."""
    
    class TipoMovimiento(models.TextChoices):
        INGRESO = 'ingreso', 'Ingreso'
        EGRESO_DISPENSACION = 'egreso_disp', 'Egreso por Dispensación'
        EGRESO_MERMA = 'egreso_merma', 'Egreso por Merma / Vencimiento'
        TRASPASO_BODEGA_VITRINA = 'traspaso_bv', 'Traspaso Bodega → Vitrina'
        TRASPASO_VITRINA_BODEGA = 'traspaso_vb', 'Traspaso Vitrina → Bodega'
        AJUSTE = 'ajuste', 'Ajuste de Inventario'
        EGRESO_CARRO = 'egreso_carro', 'Egreso a Carro Clínico'

    lote = models.ForeignKey(
        Lote,
        on_delete=models.PROTECT,
        related_name='movimientos',
        verbose_name='Lote'
    )
    tipo = models.CharField(
        max_length=20,
        choices=TipoMovimiento.choices,
        verbose_name='Tipo de movimiento'
    )
    cantidad = models.IntegerField(verbose_name='Cantidad')
    cantidad_anterior = models.PositiveIntegerField(verbose_name='Stock anterior')
    cantidad_posterior = models.PositiveIntegerField(verbose_name='Stock posterior')
    motivo = models.TextField(blank=True, verbose_name='Motivo / Observación')
    usuario = models.ForeignKey(
        'core.Usuario',
        on_delete=models.PROTECT,
        related_name='movimientos_stock',
        verbose_name='Usuario responsable'
    )
    ubicacion_origen = models.ForeignKey(
        Ubicacion,
        on_delete=models.PROTECT,
        related_name='movimientos_origen',
        null=True,
        blank=True,
        verbose_name='Ubicación origen'
    )
    ubicacion_destino = models.ForeignKey(
        Ubicacion,
        on_delete=models.PROTECT,
        related_name='movimientos_destino',
        null=True,
        blank=True,
        verbose_name='Ubicación destino'
    )
    fecha = models.DateTimeField(auto_now_add=True, verbose_name='Fecha del movimiento')

    class Meta:
        verbose_name = 'Movimiento de stock'
        verbose_name_plural = 'Movimientos de stock'
        ordering = ['-fecha']

    def __str__(self):
        return f'{self.get_tipo_display()} - {self.lote.medicamento.nombre_generico} ({self.cantidad})'


class OrdenAbastecimiento(models.Model):
    """
    Orden de Pedido / Solicitud de Remesa a CENABAST o Droguería ante quiebre de stock (RF-04, RF-06).
    Permite generar pedidos automáticos cuando un fármaco cae bajo su stock_minimo
    y recepcionar la remesa creando los nuevos lotes FEFO en Bodega Central.
    """
    class TipoOrden(models.TextChoices):
        CENABAST = 'cenabast', 'Remesa Ministerial CENABAST'
        URGENCIA_QUIEBRE = 'urgencia', 'Pedido Urgente por Quiebre de Stock'
        CONVENIO_MARCO = 'convenio', 'Adquisición Directa / Servicio de Salud'

    class EstadoOrden(models.TextChoices):
        PENDIENTE = 'pendiente', 'Pendiente Visación Q.F.'
        ENVIADA = 'enviada', 'Aprobada y Enviada a CENABAST'
        RECEPCIONADA = 'recepcionada', 'Recepcionada en Bodega Central'
        ANULADA = 'anulada', 'Anulada'

    numero_orden = models.CharField(max_length=30, unique=True, verbose_name='N° Orden / Folio CENABAST')
    tipo = models.CharField(
        max_length=20,
        choices=TipoOrden.choices,
        default=TipoOrden.URGENCIA_QUIEBRE,
        verbose_name='Tipo de abastecimiento'
    )
    estado = models.CharField(
        max_length=20,
        choices=EstadoOrden.choices,
        default=EstadoOrden.PENDIENTE,
        verbose_name='Estado de la orden'
    )
    proveedor = models.CharField(
        max_length=200,
        default='CENABAST - Central de Abastecimiento del S.N.S.S.',
        verbose_name='Proveedor / Organismo'
    )
    guia_despacho = models.CharField(
        max_length=50,
        blank=True,
        verbose_name='N° Guía de Despacho Recepcionada'
    )
    solicitante = models.ForeignKey(
        'core.Usuario',
        on_delete=models.PROTECT,
        related_name='ordenes_solicitadas',
        verbose_name='Solicitado por'
    )
    aprobador_qf = models.ForeignKey(
        'core.Usuario',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='ordenes_aprobadas',
        verbose_name='Visado por Químico Farmacéutico'
    )
    generada_automaticamente = models.BooleanField(
        default=False,
        verbose_name='Generada automáticamente por alerta de quiebre'
    )
    observaciones = models.TextField(blank=True, verbose_name='Justificación / Observaciones')
    fecha_emision = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de emisión')
    fecha_recepcion = models.DateTimeField(null=True, blank=True, verbose_name='Fecha de recepción en bodega')

    class Meta:
        verbose_name = 'Orden de abastecimiento CENABAST'
        verbose_name_plural = 'Órdenes de abastecimiento CENABAST'
        ordering = ['-fecha_emision']

    def __str__(self):
        return f'{self.numero_orden} ({self.get_estado_display()})'

    @property
    def total_unidades_solicitadas(self):
        return sum(d.cantidad_solicitada for d in self.detalles.all())


class DetalleOrdenAbastecimiento(models.Model):
    """Detalle de medicamentos e insumos solicitados en una Orden de Abastecimiento."""
    orden = models.ForeignKey(
        OrdenAbastecimiento,
        on_delete=models.CASCADE,
        related_name='detalles',
        verbose_name='Orden de abastecimiento'
    )
    medicamento = models.ForeignKey(
        Medicamento,
        on_delete=models.PROTECT,
        related_name='detalles_abastecimiento',
        verbose_name='Medicamento / Insumo'
    )
    stock_al_solicitar = models.PositiveIntegerField(
        default=0,
        verbose_name='Stock existente al solicitar'
    )
    cantidad_solicitada = models.PositiveIntegerField(
        verbose_name='Cantidad solicitada a CENABAST'
    )
    cantidad_recibida = models.PositiveIntegerField(
        default=0,
        verbose_name='Cantidad recepcionada'
    )
    lote_recibido = models.ForeignKey(
        Lote,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recepciones_cenabast',
        verbose_name='Lote ingresado en Bodega Central'
    )

    class Meta:
        verbose_name = 'Detalle de orden de abastecimiento'
        verbose_name_plural = 'Detalles de orden de abastecimiento'

    def __str__(self):
        return f'{self.medicamento.nombre_generico} x{self.cantidad_solicitada}'

