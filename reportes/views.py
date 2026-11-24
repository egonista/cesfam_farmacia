"""
Vistas del módulo Reportes del Sistema CESFAM Farmacia.
Dashboard gerencial, exportación PDF/Excel.
"""
import io
import json
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.db.models import Count, Sum

from dispensacion.models import Dispensacion, Receta
from farmacia.models import Medicamento, Lote, CategoriaMedicamento
from core.decorators import rol_requerido


@rol_requerido(
    'admin', 'quimico',
    motivo='Los reportes gerenciales y normativos están reservados al Administrador y al Químico Farmacéutico.'
)
def index(request):
    """Dashboard gerencial con KPIs y reportes."""
    return render(request, 'reportes/index.html')


@rol_requerido(
    'admin', 'quimico',
    motivo='La exportación global de reportes PDF está reservada al Administrador y al Químico Farmacéutico.'
)
def exportar_pdf(request):
    """Exportar reporte a PDF."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter)
    styles = getSampleStyleSheet()
    elements = []

    # Título
    elements.append(Paragraph('CESFAM Farmacia - Reporte de Stock', styles['Title']))
    elements.append(Paragraph(f'Fecha: {date.today().strftime("%d/%m/%Y")}', styles['Normal']))
    elements.append(Spacer(1, 20))

    # Tabla de medicamentos
    data = [['Código', 'Medicamento', 'Concentración', 'Stock Total', 'Stock Mín.', 'Estado']]
    for med in Medicamento.objects.filter(activo=True):
        estado = '⚠️ QUIEBRE' if med.en_quiebre else '✅ OK'
        data.append([
            med.codigo, med.nombre_generico, med.concentracion,
            str(med.stock_total), str(med.stock_minimo), estado
        ])

    table = Table(data)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1a5276')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('ALIGN', (3, 0), (4, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
    ]))
    elements.append(table)

    doc.build(elements)
    buffer.seek(0)

    response = HttpResponse(buffer, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="reporte_stock_cesfam_{date.today()}.pdf"'
    return response


@rol_requerido(
    'admin', 'quimico',
    motivo='La exportación global de planillas Excel está reservada al Administrador y al Químico Farmacéutico.'
)
def exportar_excel(request):
    """Exportar reporte a Excel (XLSX)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment

    wb = Workbook()

    # Hoja 1: Medicamentos y Stock
    ws = wb.active
    ws.title = 'Stock Medicamentos'

    header_fill = PatternFill(start_color='1a5276', end_color='1a5276', fill_type='solid')
    header_font = Font(color='FFFFFF', bold=True, size=10)

    headers = ['Código', 'Medicamento', 'Concentración', 'Forma Farm.', 'Categoría', 'Stock Total', 'Stock Mín.', 'En Quiebre', 'Controlado']
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal='center')

    for row, med in enumerate(Medicamento.objects.filter(activo=True).select_related('categoria'), 2):
        ws.cell(row=row, column=1, value=med.codigo)
        ws.cell(row=row, column=2, value=med.nombre_generico)
        ws.cell(row=row, column=3, value=med.concentracion)
        ws.cell(row=row, column=4, value=med.forma_farmaceutica)
        ws.cell(row=row, column=5, value=med.categoria.nombre)
        ws.cell(row=row, column=6, value=med.stock_total)
        ws.cell(row=row, column=7, value=med.stock_minimo)
        ws.cell(row=row, column=8, value='SÍ' if med.en_quiebre else 'NO')
        ws.cell(row=row, column=9, value='SÍ' if med.es_controlado else 'NO')

    # Hoja 2: Lotes
    ws2 = wb.create_sheet('Lotes')
    headers2 = ['Lote', 'Medicamento', 'Ubicación', 'Cantidad', 'F. Vencimiento', 'Días Restantes', 'Alerta']
    for col, header in enumerate(headers2, 1):
        cell = ws2.cell(row=1, column=col, value=header)
        cell.fill = header_fill
        cell.font = header_font

    for row, lote in enumerate(Lote.objects.filter(activo=True).select_related('medicamento', 'ubicacion').order_by('fecha_vencimiento'), 2):
        ws2.cell(row=row, column=1, value=lote.numero_lote)
        ws2.cell(row=row, column=2, value=lote.medicamento.nombre_generico)
        ws2.cell(row=row, column=3, value=lote.ubicacion.nombre)
        ws2.cell(row=row, column=4, value=lote.cantidad_actual)
        ws2.cell(row=row, column=5, value=lote.fecha_vencimiento.strftime('%d/%m/%Y'))
        ws2.cell(row=row, column=6, value=lote.dias_para_vencer)
        ws2.cell(row=row, column=7, value=lote.alerta_vencimiento.upper())

    # Ajustar anchos
    for ws_sheet in [ws, ws2]:
        for col in ws_sheet.columns:
            max_length = max(len(str(cell.value or '')) for cell in col)
            ws_sheet.column_dimensions[col[0].column_letter].width = min(max_length + 4, 40)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)

    response = HttpResponse(
        buffer,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="reporte_cesfam_{date.today()}.xlsx"'
    return response


@login_required
def api_dashboard_data(request):
    """API para datos del dashboard en tiempo real."""
    hoy = date.today()
    hace_7 = hoy - timedelta(days=7)

    # Dispensaciones últimos 7 días
    labels = []
    valores = []
    for i in range(6, -1, -1):
        dia = hoy - timedelta(days=i)
        labels.append(dia.strftime('%d/%m'))
        valores.append(Dispensacion.objects.filter(fecha__date=dia).count())

    # Stock por categoría
    categorias = CategoriaMedicamento.objects.all()
    cat_data = {
        'labels': [c.nombre for c in categorias],
        'values': [sum(m.stock_total for m in c.medicamentos.filter(activo=True)) for c in categorias],
    }

    return JsonResponse({
        'dispensaciones': {'labels': labels, 'values': valores},
        'stock_categorias': cat_data,
        'kpis': {
            'dispensaciones_hoy': Dispensacion.objects.filter(fecha__date=hoy).count(),
            'recetas_pendientes': Receta.objects.filter(estado='pendiente').count(),
            'medicamentos_quiebre': sum(1 for m in Medicamento.objects.filter(activo=True) if m.en_quiebre),
            'lotes_vencidos': Lote.objects.filter(activo=True, fecha_vencimiento__lte=hoy).count(),
        }
    })
