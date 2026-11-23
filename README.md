# Sistema Web de Gestión y Simulación Asistencial para Farmacia de Atención Primaria de Salud (CESFAM)

**Carrera:** Analista Programador  
**Asignatura:** Proyecto Integrado (`AP-N4-C1`, 2026)  
**Institución:** Universidad Tecnológica de Chile - INACAP  
**Autores:** Egon Muñoz Muttel & Renato Suazo Burgos  
**Docente Evaluador:** Juan Mir Castillo  
**Área Solicitante:** Dirección de Carrera - Nataly Caamaño  

---

## 🏥 Descripción del Sistema

Plataforma web integral diseñada para la gestión operacional y la simulación docente de una **Farmacia Asistencial de Atención Primaria de Salud (CESFAM)** en Chile:
- **Dispensación Asistencial Gratuita ($0 Copago):** Exclusión total de cobros comerciales, POS o DTE tributarios.
- **Motor Algorítmico FEFO (*First Expired, First Out*):** Segregación física entre **Bodega Central** y **Vitrina de Dispensación**, semáforo de caducidad a 30/60/90 días, bloqueo automático de lotes vencidos y justificación técnica obligatoria ante overrides.
- **Órdenes de Abastecimiento y Recepción de Remesas CENABAST:** Generación automática ante quiebre de stock y confección manual editable multi-ítem (con incorporación de nuevos fármacos al catálogo), visación del Químico Farmacéutico y recepción conforme en Bodega Central.
- **Trazabilidad de Retiro por Tercero Autorizado:** Validación de RUT chileno mediante algoritmo **Módulo 11**, parentesco, teléfono e impresión de Comprobante Oficial de Entrega con firmas.
- **Programas de Salud GES/AUGE y Pacientes Crónicos:** Control de canastas farmacológicas oficiales y saldo de cuotas anuales.
- **Libro Oficial Digital de Medicamentos Controlados (ISP D.S. 404/83 y 405/83):** Registro foliado inmutable con validación de segundo factor (**2FA / PIN**).
- **Carros Clínicos (Carro de Paro y Unidosis):** Plantilla canónica, consumo en emergencia, estado `Incompleto - En Reposición`, reposición FEFO y registro de precinto de seguridad (`PREC-2026-XXXX`).
- **Bitácora Forense Inmutable (*Append-Only*) y Seguridad (Ley N° 21.719):** Almacenada en **PostgreSQL 18 (`JSONB`)**, hashes **Argon2id**, matriz **RBAC** para 4 roles con selector rápido de 1-Clic y cifrado simétrico **AES/Fernet**.

---

## 🚀 Puesta en Marcha Local

### 1. Requisitos
- Python 3.12+
- PostgreSQL 18 corriendo en `localhost:5432` (Base de datos: `cesfam_farmacia_db`)

### 2. Instalación y Ejecución
```powershell
python -m venv venv
.\venv\Scripts\pip.exe install -r requirements.txt
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py seed_cesfam
.\venv\Scripts\python.exe manage.py runserver 127.0.0.1:8000
```

### 3. Ejecución de Pruebas Automatizadas (QA) y Benchmark
```powershell
.\venv\Scripts\python.exe manage.py test core
.\venv\Scripts\python.exe benchmark_rnf03_cesfam.py
```

---

## 🔐 Credenciales de Simulación Docente (Contraseña única: `Inacap2026!`)

| Rol Sanitario (RBAC) | Usuario | Correo | PIN 2FA |
| :--- | :--- | :--- | :--- |
| **Administrador** | `admin` | `egon.munoz@cesfam.cl` | `123456` |
| **Químico Farmacéutico** | `qf_suazo` | `renato.suazo@cesfam.cl` | `123456` |
| **Técnico en Farmacia** | `tecnico_alvarez` | `rodrigo.alvarez@cesfam.cl` | — |
| **Personal Clínico** | `enfermera_gonzalez` | `camila.gonzalez@cesfam.cl` | — |
