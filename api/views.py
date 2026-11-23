"""
Vistas API REST del Sistema CESFAM Farmacia.
"""
from rest_framework import viewsets, serializers
from rest_framework.permissions import IsAuthenticated

from core.models import Paciente
from farmacia.models import Medicamento, Lote
from dispensacion.models import Receta, Dispensacion


class MedicamentoSerializer(serializers.ModelSerializer):
    stock_total = serializers.ReadOnlyField()
    en_quiebre = serializers.ReadOnlyField()

    class Meta:
        model = Medicamento
        fields = '__all__'


class LoteSerializer(serializers.ModelSerializer):
    dias_para_vencer = serializers.ReadOnlyField()
    alerta_vencimiento = serializers.ReadOnlyField()

    class Meta:
        model = Lote
        fields = '__all__'


class PacienteSerializer(serializers.ModelSerializer):
    nombre_completo = serializers.ReadOnlyField()

    class Meta:
        model = Paciente
        fields = '__all__'


class RecetaSerializer(serializers.ModelSerializer):
    esta_vigente = serializers.ReadOnlyField()

    class Meta:
        model = Receta
        fields = '__all__'


class DispensacionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Dispensacion
        fields = '__all__'


class MedicamentoViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Medicamento.objects.filter(activo=True)
    serializer_class = MedicamentoSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['categoria', 'es_controlado', 'activo']
    search_fields = ['codigo', 'nombre_generico', 'nombre_comercial']


class LoteViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Lote.objects.filter(activo=True).order_by('fecha_vencimiento')
    serializer_class = LoteSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['medicamento', 'ubicacion', 'activo']


class PacienteViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Paciente.objects.filter(activo=True)
    serializer_class = PacienteSerializer
    permission_classes = [IsAuthenticated]
    search_fields = ['rut', 'nombres', 'apellido_paterno']


class RecetaViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Receta.objects.all()
    serializer_class = RecetaSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ['estado', 'tipo', 'paciente']


class DispensacionViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Dispensacion.objects.all()
    serializer_class = DispensacionSerializer
    permission_classes = [IsAuthenticated]
