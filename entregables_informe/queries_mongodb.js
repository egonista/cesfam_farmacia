/**
 * Colección de Consultas y Operaciones NoSQL en MongoDB (mongosh)
 * Sistema Web de Gestión y Simulación Asistencial para Farmacia CESFAM
 * Autores: Egon Muñoz Muttel y Renato Suazo Burgos - INACAP 2026
 * 
 * Base de datos: cesfam_nosql_db
 * Colecciones: auditoria_inmutable, recursos_fhir, alertas_sistema
 */

// Seleccionar la base de datos
use cesfam_nosql_db;

print("=========================================================");
print("  CONSULTAS OPERACIONALES Y DE AUDITORÍA EN MONGODB");
print("=========================================================");

// ---------------------------------------------------------------
// 1. COLECCIÓN: auditoria_inmutable (RNF-04 y RF-17)
// ---------------------------------------------------------------

print("\n--- 1.1 Últimas transacciones críticas registradas (patrón append-only) ---");
db.auditoria_inmutable.find().sort({ timestamp: -1 }).limit(5).pretty();

print("\n--- 1.2 Auditoría de Anulaciones u Overrides del Algoritmo FEFO ---");
// Permite auditar cada vez que un Químico Farmacéutico forzó un lote distinto al sugerido
db.auditoria_inmutable.find(
    { accion: { $regex: "Override FEFO", $options: "i" } },
    { timestamp: 1, usuario_username: 1, rol: 1, entidad_afectada: 1, valores_anteriores: 1, valores_nuevos: 1 }
).pretty();

print("\n--- 1.3 Auditoría de transacciones sobre el Libro de Controlados (D.S. 404/405) ---");
db.auditoria_inmutable.find(
    { entidad_afectada: { $regex: "LibroControlados|Controlado", $options: "i" } }
).sort({ timestamp: -1 }).pretty();

print("\n--- 1.4 Resumen de acciones por rol de usuario (Pipeline de Agregación) ---");
db.auditoria_inmutable.aggregate([
    {
        $group: {
            _id: "$rol",
            total_transacciones: { $sum: 1 },
            acciones_distintas: { $addToSet: "$accion" }
        }
    },
    { $sort: { total_transacciones: -1 } }
]);


// ---------------------------------------------------------------
// 2. COLECCIÓN: recursos_fhir (Estándar HL7 / FHIR R4)
// ---------------------------------------------------------------

print("\n--- 2.1 Búsqueda de Recurso Patient por Cédula de Identidad (RUN/RUT Chileno) ---");
db.recursos_fhir.find({
    resourceType: "Patient",
    "identifier.value": "11.234.567-1"
}).pretty();

print("\n--- 2.2 Búsqueda de Prescripciones Activas (MedicationRequest) por Paciente ---");
db.recursos_fhir.find({
    resourceType: "MedicationRequest",
    "subject.reference": "Patient/paciente-11234567-1"
}).pretty();

print("\n--- 2.3 Trazabilidad de Dispensación (MedicationDispense) y Retiro por Tercero ---");
db.recursos_fhir.find({
    resourceType: "MedicationDispense",
    "note.text": { $regex: "tercero autorizado", $options: "i" }
}, {
    id: 1,
    medicationCodeableConcept: 1,
    quantity: 1,
    whenHandedOver: 1,
    note: 1
}).pretty();


// ---------------------------------------------------------------
// 3. COLECCIÓN: alertas_sistema (RF-06 y RF-07)
// ---------------------------------------------------------------

print("\n--- 3.1 Alertas Sanitarias Críticas no atendidas (Vencimiento <= 30 días) ---");
db.alertas_sistema.find({
    tipo: { $in: ["vencimiento_critico", "vencimiento_30"] },
    leido: false
}).sort({ dias_restantes: 1 }).pretty();

print("\n--- 3.2 Alertas de Quiebre o Riesgo de Desabastecimiento de Stock ---");
db.alertas_sistema.find({
    tipo: "quiebre_stock"
}).pretty();

print("\n--- 3.3 Agrupación de alertas por nivel de criticidad (Pipeline de Agregación) ---");
db.alertas_sistema.aggregate([
    {
        $group: {
            _id: "$nivel",
            total_alertas: { $sum: 1 },
            medicamentos_afectados: { $addToSet: "$medicamento" }
        }
    },
    { $sort: { total_alertas: -1 } }
]);

print("\n[FIN DE CONSULTAS MONGODB]");
