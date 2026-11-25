/**
 * CESFAM Farmacia - JavaScript principal
 * Sistema de Gestión y Simulación Asistencial
 * Incluye: Validación RUT (Módulo 11), utilidades de formulario
 */

'use strict';

// ============================================================
// VALIDACIÓN DE RUT CHILENO (Módulo 11) - Client-side
// ============================================================

/**
 * Limpia un RUT eliminando puntos, guiones y espacios.
 * @param {string} rut - RUT a limpiar
 * @returns {string} RUT limpio en mayúsculas
 */
function limpiarRut(rut) {
    return rut.replace(/[.\-\s]/g, '').toUpperCase();
}

/**
 * Calcula el dígito verificador de un RUT chileno usando el Módulo 11.
 * @param {string} cuerpo - Cuerpo numérico del RUT (sin DV)
 * @returns {string} Dígito verificador calculado ('0'-'9' o 'K')
 */
function calcularDigitoVerificador(cuerpo) {
    let suma = 0;
    let multiplicador = 2;
    for (let i = cuerpo.length - 1; i >= 0; i--) {
        suma += parseInt(cuerpo[i]) * multiplicador;
        multiplicador = multiplicador < 7 ? multiplicador + 1 : 2;
    }
    const resto = 11 - (suma % 11);
    if (resto === 11) return '0';
    if (resto === 10) return 'K';
    return String(resto);
}

/**
 * Valida un RUT chileno completo (con dígito verificador).
 * @param {string} rut - RUT a validar (acepta formatos variados)
 * @returns {boolean} true si el RUT es válido
 */
function validarRut(rut) {
    if (!rut) return false;
    const rutLimpio = limpiarRut(rut);
    if (rutLimpio.length < 8) return false;
    
    const cuerpo = rutLimpio.slice(0, -1);
    const dvIngresado = rutLimpio.slice(-1);
    
    if (!/^\d+$/.test(cuerpo)) return false;
    if (cuerpo.length < 7 || cuerpo.length > 8) return false;
    
    const dvCalculado = calcularDigitoVerificador(cuerpo);
    return dvIngresado === dvCalculado;
}

/**
 * Formatea un RUT al formato XX.XXX.XXX-X.
 * @param {string} rut - RUT a formatear
 * @returns {string} RUT formateado
 */
function formatearRut(rut) {
    const rutLimpio = limpiarRut(rut);
    if (rutLimpio.length < 2) return rut;
    
    const cuerpo = rutLimpio.slice(0, -1);
    const dv = rutLimpio.slice(-1);
    
    let formateado = '';
    for (let i = cuerpo.length - 1, j = 0; i >= 0; i--, j++) {
        if (j > 0 && j % 3 === 0) formateado = '.' + formateado;
        formateado = cuerpo[i] + formateado;
    }
    return formateado + '-' + dv;
}

// ============================================================
// VALIDACIÓN DE FORMULARIOS EN TIEMPO REAL
// ============================================================

document.addEventListener('DOMContentLoaded', function() {
    // Auto-validar todos los campos de RUT
    document.querySelectorAll('input[data-validate-rut]').forEach(function(input) {
        input.addEventListener('blur', function() {
            const valor = this.value.trim();
            if (valor) {
                if (validarRut(valor)) {
                    this.classList.remove('is-invalid');
                    this.classList.add('is-valid');
                    this.value = formatearRut(valor);
                    // Limpiar mensaje de error
                    const feedback = this.nextElementSibling;
                    if (feedback && feedback.classList.contains('invalid-feedback')) {
                        feedback.textContent = '';
                    }
                } else {
                    this.classList.remove('is-valid');
                    this.classList.add('is-invalid');
                    let feedback = this.nextElementSibling;
                    if (!feedback || !feedback.classList.contains('invalid-feedback')) {
                        feedback = document.createElement('div');
                        feedback.classList.add('invalid-feedback');
                        this.parentNode.insertBefore(feedback, this.nextSibling);
                    }
                    feedback.textContent = 'El RUT ingresado no es válido. Verifique los dígitos y el guión.';
                }
            }
        });
    });

    // Toggle tercero autorizado
    const checkTercero = document.getElementById('id_retiro_tercero');
    const divTercero = document.getElementById('div-tercero-autorizado');
    if (checkTercero && divTercero) {
        checkTercero.addEventListener('change', function() {
            divTercero.style.display = this.checked ? 'block' : 'none';
            // Hacer campos requeridos
            divTercero.querySelectorAll('input[data-required-if-tercero]').forEach(function(inp) {
                inp.required = checkTercero.checked;
            });
        });
        // Estado inicial
        divTercero.style.display = checkTercero.checked ? 'block' : 'none';
    }

    // Auto-dismiss de alertas después de 5 segundos
    document.querySelectorAll('.alert-dismissible').forEach(function(alert) {
        setTimeout(function() {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            bsAlert.close();
        }, 5000);
    });

    // Nota: las confirmaciones [data-confirm] se manejan globalmente mediante el modal #modalConfirmacionGlobal en base.html.

    // Inicializar tooltips de Bootstrap
    const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    tooltipTriggerList.forEach(function(el) {
        new bootstrap.Tooltip(el);
    });
});

// ============================================================
// FEFO - Helpers para selección de lotes
// ============================================================

/**
 * Resalta visualmente el lote sugerido por FEFO en una tabla.
 * @param {string} tableId - ID de la tabla de lotes
 */
function resaltarLoteFEFO(tableId) {
    const table = document.getElementById(tableId);
    if (!table) return;
    
    const rows = table.querySelectorAll('tbody tr');
    rows.forEach(function(row, index) {
        row.classList.remove('table-success', 'table-danger');
        const vencido = row.dataset.vencido === 'true';
        if (vencido) {
            row.classList.add('table-danger');
        } else if (index === 0) {
            row.classList.add('table-success');
            const badge = row.querySelector('.fefo-badge');
            if (badge) badge.textContent = '✓ FEFO Sugerido';
        }
    });
}

// ============================================================
// DASHBOARD - Inicialización de gráficos Chart.js
// ============================================================

/**
 * Crea un gráfico de dispensaciones por día.
 * @param {string} canvasId - ID del elemento canvas
 * @param {Object} data - Datos del gráfico {labels: [], values: []}
 */
function crearGraficoDispensaciones(canvasId, data) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    
    new Chart(ctx, {
        type: 'line',
        data: {
            labels: data.labels,
            datasets: [{
                label: 'Recetas Dispensadas',
                data: data.values,
                borderColor: '#1a5276',
                backgroundColor: 'rgba(26, 82, 118, 0.1)',
                fill: true,
                tension: 0.4,
                pointRadius: 4,
                pointBackgroundColor: '#1a5276',
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
            },
            scales: {
                y: { beginAtZero: true, ticks: { stepSize: 1 } }
            }
        }
    });
}

/**
 * Crea un gráfico de stock por categoría.
 * @param {string} canvasId - ID del canvas
 * @param {Object} data - Datos del gráfico
 */
function crearGraficoStock(canvasId, data) {
    const ctx = document.getElementById(canvasId);
    if (!ctx) return;
    
    new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: data.labels,
            datasets: [{
                data: data.values,
                backgroundColor: [
                    '#1a5276', '#27ae60', '#f39c12', '#c0392b',
                    '#8e44ad', '#2980b9', '#d35400', '#16a085'
                ],
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { position: 'bottom' }
            }
        }
    });
}
