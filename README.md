# Simulador Web de Farmacia Asistencial CESFAM — INACAP

Plataforma web de gestión y simulación docente para una **Farmacia Asistencial de Atención Primaria de Salud (CESFAM)** en Chile, orientada a la formación práctica por roles clínicos y farmacéuticos (dispensación gratuita `$0 copago`, control **FEFO**, garantías **GES/AUGE**, libro foliado de **Controlados ISP**, abastecimiento **CENABAST**, **Carros Clínicos**, gestión de cursos/secciones con importación masiva y **Escenarios de Simulación** en tiempo real).

- **Institución:** Universidad Tecnológica de Chile — INACAP
- **Carrera / Asignatura:** Analista Programador · Proyecto Integrado (`AP-N4-C1`, 2026)
- **Autores:** Egon Muñoz Muttel & Renato Suazo Burgos

---

## Requisitos previos

- **Python 3.12+** (probado en Python 3.12 – 3.14)
- **Git**
- *(Opcional)* PostgreSQL 16+ si se desea usar en vez de SQLite. **Por defecto funciona de inmediato con SQLite (`db.sqlite3`) sin instalar bases de datos adicionales.**

---

## Instalación y puesta en marcha (2 minutos)

### 1. Clonar el repositorio
```bash
git clone https://github.com/egonista/cesfam_farmacia.git
cd cesfam_farmacia
```

### 2. Crear y activar el entorno virtual

**Windows (PowerShell):**
```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
```

**Windows (CMD):**
```cmd
python -m venv venv
venv\Scripts\activate.bat
```

**macOS / Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Instalar dependencias, migrar y cargar datos iniciales
```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_cesfam
```
> El comando `python manage.py seed_cesfam` es **idempotente** (puedes ejecutarlo más de una vez sin duplicar datos) y crea los 4 roles, secciones (`Docencia`, `AP-N4-C1`), arsenal con 9 medicamentos y 2 insumos clínicos, 17 lotes FEFO (vigentes, críticos y vencidos) con Kardex inicial, Carros Clínicos con consumo de prueba, pacientes GES/crónicos, recetas variadas, asientos del Libro de Controlados y los 2 escenarios de simulación iniciales.

### 4. Iniciar el servidor local
```bash
python manage.py runserver 127.0.0.1:8000
```
Abre **http://127.0.0.1:8000/** en tu navegador (incluye botones de **Acceso Rápido 1-Clic** en `/login/` para facilitar presentaciones locales).

*(Opcional — PostgreSQL)*: Si deseas conectar a PostgreSQL local, copia `.env.example` como `.env`, ajusta `DB_ENGINE=postgresql` y tus credenciales locales, y ejecuta `migrate` + `seed_cesfam`.

---

## Credenciales de prueba (4 roles RBAC)

**Contraseña única para los 4 usuarios:** `Inacap2026!`

| Rol (RBAC) | Usuario | Correo | PIN 2FA | Qué probar con este rol |
| :--- | :--- | :--- | :--- | :--- |
| **Administrador (Docente)** | `admin` | `egon.munoz@cesfam.cl` | `123456` | Dashboard de supervisión y bitácora, **Usuarios, Secciones/Cursos e Importación Masiva `.csv`/`.xlsx`**, **Escenarios de Simulación** (CRUD, modalidad libre/incidencias, *Banco de Pacientes*, actualización en vivo sin F5), **Arsenal** (alta con lote inicial en 1 paso), **Inventario/Lotes** (Traspasos, Cuarentena, Ajuste Manual), **CENABAST** (crear/aprobar/recepcionar), **Carros Clínicos** (CRUD plantilla, consumo y reposición), **Reportes (Excel/PDF)**, **Descargar Respaldo BD (JSON)** y selector rápido `/simular-rol/`. |
| **Químico Farmacéutico** | `qf_suazo` | `renato.suazo@cesfam.cl` | `123456` | **Libro Oficial de Controlados ISP** (con PIN `123456`), autorización de **recetas retenidas/controladas**, aprobación de **Pedidos CENABAST**, pase a **cuarentena/baja** de lotes vencidos, alta/edición en **Arsenal** (1 paso) y plantilla de **Carros Clínicos**, **Reportes (Excel/PDF)** y bloqueo `403` en Usuarios, Respaldo BD y `/simular-rol/`. |
| **Técnico en Farmacia** | `tecnico_alvarez` | `rodrigo.alvarez@cesfam.cl` | — | **Ventanilla de Dispensación** (motor **FEFO**, filtrado en vivo, bloqueo de recetas vencidas y controladas sin visación Q.F., retiro por tercero autorizado), **Traspasos Bodega → Vitrina**, ingreso de lotes estándar, reposición y resellado de **Carros Clínicos**, y bloqueo `403` en Usuarios, Controlados ISP, Aprobación CENABAST y `/simular-rol/`. |
| **Personal Clínico (Enfermería)** | `enfermera_gonzalez` | `camila.gonzalez@cesfam.cl` | — | Dashboard clínico, consulta de disponibilidad en **Arsenal Farmacológico**, registro de **consumos de emergencia en Carro de Paro** (rotura de precinto), y bloqueo `403` en Pacientes, Recetas, Dispensación, Lotes y Usuarios. |

---

## Verificación rápida y pruebas automatizadas

```bash
# 1. Suite completa de pruebas unitarias, integración, seguridad de archivos y rendimiento (32 tests)
python manage.py test core -v 2

# 2. Smoke test de vistas, matriz RBAC de los 4 roles, APIs JSON, Respaldo BD y exportación Excel/PDF
python verify_views.py
```
