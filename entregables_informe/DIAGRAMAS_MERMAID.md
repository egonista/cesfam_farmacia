# Diagramas de Arquitectura y Modelo Entidad-Relación (MER)
## Sistema Web de Gestión y Simulación Asistencial para Farmacia CESFAM
**Autores:** Egon Muñoz Muttel, Renato Suazo Burgos  
**Asignatura:** Proyecto Integrado - INACAP 2026  
**Profesor Guía:** Juan Mir Castillo  

---

## 1. Diagrama Entidad-Relación (MER) - Base de Datos PostgreSQL

```mermaid
erDiagram
    USUARIO {
        int id PK
        string username
        string password
        string rut UK
        string first_name
        string last_name
        string email
        string rol "admin, quimico, tecnico, clinico"
        string totp_secret
        string pin_seguridad
        boolean activo_sistema
        datetime fecha_creacion
    }

    PACIENTE {
        int id PK
        string rut UK
        string nombres
        string apellido_paterno
        string apellido_materno
        date fecha_nacimiento
        string sexo
        string prevision "fonasa_a, fonasa_b, fonasa_c, fonasa_d, prais"
        boolean cronico
        boolean activo
    }

    MEDICO_PRESCRIPTOR {
        int id PK
        string rut UK
        string nombres
        string apellido_paterno
        string apellido_materno
        string especialidad
        string registro_sis UK
        boolean habilitado
    }

    CATEGORIA_MEDICAMENTO {
        int id PK
        string nombre UK
        string descripcion
        boolean es_controlado
    }

    MEDICAMENTO {
        int id PK
        string codigo UK
        string nombre_generico
        string nombre_comercial
        string concentracion
        string forma_farmaceutica
        string unidad_medida
        int categoria_id FK
        int stock_minimo
        int stock_maximo
        boolean requiere_receta
        boolean es_controlado
        boolean activo
    }

    UBICACION {
        int id PK
        string nombre
        string tipo "bodega, vitrina"
        string descripcion
        boolean activa
    }

    LOTE {
        int id PK
        int medicamento_id FK
        string numero_lote
        date fecha_fabricacion
        date fecha_vencimiento
        int cantidad_inicial
        int cantidad_actual
        int ubicacion_id FK
        string proveedor
        boolean activo
    }

    MOVIMIENTO_STOCK {
        int id PK
        int lote_id FK
        string tipo
        int cantidad
        int cantidad_anterior
        int cantidad_posterior
        string motivo
        int usuario_id FK
        int ubicacion_origen_id FK
        int ubicacion_destino_id FK
        datetime fecha
    }

    RECETA {
        int id PK
        string numero_receta UK
        int paciente_id FK
        int medico_id FK
        string tipo "simple, retenida, cheque, cronica"
        string estado "pendiente, parcial, total, anulada, vencida"
        string diagnostico
        date fecha_emision
        date fecha_vencimiento
        string observaciones
    }

    DETALLE_RECETA {
        int id PK
        int receta_id FK
        int medicamento_id FK
        int cantidad_prescrita
        int cantidad_dispensada
        string posologia
        int dias_tratamiento
    }

    TERCERO_AUTORIZADO {
        int id PK
        string rut
        string nombres
        string apellido_paterno
        string apellido_materno
        string parentesco
        string telefono
    }

    DISPENSACION {
        int id PK
        int receta_id FK
        int usuario_dispensador_id FK
        boolean retiro_tercero
        int tercero_autorizado_id FK
        decimal copago
        string observaciones
        datetime fecha
    }

    DETALLE_DISPENSACION {
        int id PK
        int dispensacion_id FK
        int detalle_receta_id FK
        int lote_id FK
        int cantidad
        boolean fefo_override
        string justificacion_override
    }

    PATOLOGIA_GES {
        int id PK
        string codigo UK
        string nombre
        string descripcion
        boolean activa
    }

    CANASTA_GES {
        int id PK
        int patologia_id FK
        int medicamento_id FK
        int cantidad_por_cuota
        int cuotas_autorizadas
    }

    INSCRIPCION_GES {
        int id PK
        int paciente_id FK
        int patologia_id FK
        date fecha_inscripcion
        date fecha_inicio_periodo
        date fecha_fin_periodo
        boolean activa
    }

    CUOTA_GES {
        int id PK
        int inscripcion_id FK
        int canasta_id FK
        int numero_cuota
        int cantidad_entregada
        int dispensacion_id FK
        datetime fecha_entrega
    }

    LIBRO_CONTROLADOS {
        int id PK
        int folio UK
        int medicamento_id FK
        int lote_id FK
        string tipo_movimiento
        int cantidad
        int saldo_anterior
        int saldo_posterior
        int receta_id FK
        int paciente_id FK
        int quimico_responsable_id FK
        boolean verificacion_2fa
        string observaciones
        datetime fecha_registro
    }

    CARRO_CLINICO {
        int id PK
        string nombre
        string tipo "paro, unidosis"
        string ubicacion_fisica
        string estado "completo, incompleto, en_uso, mantenimiento"
        string numero_precinto
        datetime fecha_ultimo_precinto
        int responsable_actual_id FK
        boolean activo
    }

    PLANTILLA_ITEM_CARRO {
        int id PK
        int carro_id FK
        int medicamento_id FK
        int cantidad_requerida
        int cantidad_actual
        string ubicacion_en_carro
    }

    CONSUMO_CARRO_CLINICO {
        int id PK
        int carro_id FK
        int item_id FK
        int cantidad_consumida
        string motivo
        string paciente_atendido
        int personal_clinico_id FK
        datetime fecha
    }

    REPOSICION_CARRO {
        int id PK
        int carro_id FK
        int item_id FK
        int lote_id FK
        int cantidad_repuesta
        int usuario_farmacia_id FK
        string nuevo_precinto
        datetime fecha
    }

    %% Relaciones Principales
    CATEGORIA_MEDICAMENTO ||--o{ MEDICAMENTO : clasifica
    MEDICAMENTO ||--o{ LOTE : contiene
    UBICACION ||--o{ LOTE : almacena
    LOTE ||--o{ MOVIMIENTO_STOCK : registra
    USUARIO ||--o{ MOVIMIENTO_STOCK : ejecuta

    PACIENTE ||--o{ RECETA : posee
    MEDICO_PRESCRIPTOR ||--o{ RECETA : prescribe
    RECETA ||--|{ DETALLE_RECETA : compone
    MEDICAMENTO ||--o{ DETALLE_RECETA : indicado_en

    RECETA ||--o{ DISPENSACION : origina
    USUARIO ||--o{ DISPENSACION : dispensa
    TERCERO_AUTORIZADO ||--o{ DISPENSACION : retira_por
    DISPENSACION ||--|{ DETALLE_DISPENSACION : contiene
    DETALLE_RECETA ||--o{ DETALLE_DISPENSACION : satisface
    LOTE ||--o{ DETALLE_DISPENSACION : entrega

    PATOLOGIA_GES ||--|{ CANASTA_GES : define
    MEDICAMENTO ||--o{ CANASTA_GES : integra
    PACIENTE ||--o{ INSCRIPCION_GES : adscrito_a
    PATOLOGIA_GES ||--o{ INSCRIPCION_GES : vincula
    INSCRIPCION_GES ||--o{ CUOTA_GES : computa
    CANASTA_GES ||--o{ CUOTA_GES : descuenta
    DISPENSACION ||--o{ CUOTA_GES : asocia

    MEDICAMENTO ||--o{ LIBRO_CONTROLADOS : fiscaliza
    LOTE ||--o{ LIBRO_CONTROLADOS : audita
    USUARIO ||--o{ LIBRO_CONTROLADOS : firma
    RECETA ||--o{ LIBRO_CONTROLADOS : justifica

    CARRO_CLINICO ||--|{ PLANTILLA_ITEM_CARRO : conforma
    MEDICAMENTO ||--o{ PLANTILLA_ITEM_CARRO : estandariza
    PLANTILLA_ITEM_CARRO ||--o{ CONSUMO_CARRO_CLINICO : consume
    CARRO_CLINICO ||--o{ CONSUMO_CARRO_CLINICO : registra_en
    USUARIO ||--o{ CONSUMO_CARRO_CLINICO : reporta
    PLANTILLA_ITEM_CARRO ||--o{ REPOSICION_CARRO : repone
    LOTE ||--o{ REPOSICION_CARRO : abastece
    USUARIO ||--o{ REPOSICION_CARRO : autoriza
```

---

## 2. Modelo Arquitectural 4+1 de Kruchten

### 2.1 Vista de Casos de Uso (Escenarios)

```mermaid
flowchart TD
    subgraph Actores
        ADM["Administrador"]
        QF["Químico Farmacéutico"]
        TEC["Técnico en Farmacia"]
        ENF["Personal Clínico / Enfermería"]
    end

    subgraph CasosDeUso["Casos de Uso Principales (APS)"]
        CU01["CU-01: Dispensación Asistencial $0 Copago"]
        CU02["CU-02: Priorización Algorítmica FEFO"]
        CU03["CU-03: Validación Cobertura y Cuotas GES"]
        CU04["CU-04: Retiro por Tercero Autorizado"]
        CU05["CU-05: Libro Oficial Digital Controlados (2FA)"]
        CU06["CU-06: Gestión y Reposición Carro de Paro"]
        CU07["CU-07: Monitoreo Alertas y Vencimientos"]
        CU08["CU-08: Gestión de Usuarios y Matriz RBAC"]
    end

    ADM --> CU08
    ADM --> CU05
    ADM --> CU07

    QF --> CU02
    QF --> CU05
    QF --> CU06
    QF --> CU07

    TEC --> CU01
    TEC --> CU02
    TEC --> CU03
    TEC --> CU04
    TEC --> CU06

    ENF --> CU06
```

---

### 2.2 Vista Lógica (Estructura de Componentes de Dominio)

```mermaid
classDiagram
    class ModuloCore {
        +Usuario (RBAC)
        +Paciente (FONASA/PRAIS)
        +MedicoPrescriptor (SIS)
        +validar_rut_modulo11()
        +cifrar_aes_ley21719()
        +registrar_auditoria_mongodb()
    }

    class ModuloFarmacia {
        +Medicamento
        +Lote (FEFO)
        +Ubicacion (Bodega / Vitrina)
        +MovimientoStock
        +lotes_fefo()
        +puede_dispensar()
    }

    class ModuloDispensacion {
        +Receta
        +DetalleReceta
        +Dispensacion ($0 Copago)
        +DetalleDispensacion
        +TerceroAutorizado
        +fefo_override_check()
    }

    class ModuloGES {
        +PatologiaGES
        +CanastaGES
        +InscripcionGES
        +CuotaGES
        +validar_saldo_cuotas()
    }

    class ModuloControlados {
        +LibroControlados (D.S. 404/405)
        +verificar_pin_2fa()
        +siguiente_folio()
    }

    class ModuloCarrosClinicos {
        +CarroClinico (Paro / Unidosis)
        +PlantillaItemCarro
        +ConsumoCarroClinico
        +ReposicionCarro
        +verificar_precinto()
    }

    ModuloCore <|-- ModuloFarmacia : referencia usuarios
    ModuloFarmacia <-- ModuloDispensacion : consume lotes FEFO
    ModuloCore <-- ModuloDispensacion : valida paciente y prescriptor
    ModuloGES <-- ModuloDispensacion : valida cuotas GES
    ModuloFarmacia <-- ModuloControlados : fiscaliza stock
    ModuloFarmacia <-- ModuloCarrosClinicos : reposicion FEFO
```

---

### 2.3 Vista de Procesos

#### 2.3.1 Secuencia: Dispensación Asistencial con Lógica FEFO y Tercero Autorizado

```mermaid
sequenceDiagram
    autonumber
    actor T as Técnico en Farmacia
    participant UI as Interfaz Web (Bootstrap 5)
    participant V as Vista Dispensación
    participant ORM as PostgreSQL (Django ORM)
    participant MDB as MongoDB (Audit & FHIR)

    T->>UI: Ingresa N° Receta o RUT Paciente
    UI->>V: GET /dispensar/<receta_pk>/
    V->>ORM: Consulta Receta, Paciente y Medicamentos
    V->>ORM: Ejecuta lotes_fefo() (Ascendente por Vencimiento)
    ORM-->>V: Retorna lotes disponibles (Preselecciona el más próximo)
    V-->>UI: Renderiza vista con Lote FEFO preseleccionado
    
    T->>UI: Marca "Retiro por Tercero", ingresa datos cuidador y confirma
    UI->>V: POST /dispensar/<receta_pk>/ (Datos + RUT Tercero)
    V->>V: validar_rut_modulo11(RUT Tercero)
    
    alt RUT Tercero Inválido
        V-->>UI: Retorna Alerta de Error (Módulo 11)
    else RUT Válido
        V->>ORM: Inicia Transaction Atomic
        V->>ORM: Crea Registro TerceroAutorizado
        V->>ORM: Crea Dispensacion (Copago = $0)
        V->>ORM: Descuenta cantidad de Lote en Vitrina
        V->>ORM: Registra MovimientoStock (EGRESO_DISPENSACION)
        V->>ORM: Actualiza estado Receta (DISPENSADA_TOTAL)
        V->>ORM: Commit Transaction
        
        V->>MDB: insert_one() en auditoria_inmutable (Append-Only)
        V->>MDB: insert_one() en recursos_fhir (MedicationDispense)
        V-->>UI: Redirecciona con mensaje de éxito ($0 copago)
    end
```

#### 2.3.2 Secuencia: Emergencia en Carro de Paro y Reposición FEFO

```mermaid
sequenceDiagram
    autonumber
    actor ENF as Personal Clínico (Enfermería)
    actor QF as Químico / Técnico Farmacia
    participant UI as Interfaz Web
    participant V as Vista Carros Clínicos
    participant DB as PostgreSQL
    participant MDB as MongoDB

    ENF->>UI: Registra consumo de emergencia (10 ampollas Adrenalina)
    UI->>V: POST /carros/<id>/consumo/
    V->>DB: Registra ConsumoCarroClinico
    V->>DB: Actualiza cantidad_actual y cambia estado a "Incompleto - En Reposición"
    V->>MDB: Registra evento en auditoria_inmutable
    V-->>UI: Alerta visual de carro incompleto

    QF->>UI: Abre pantalla de reposición de Carro de Paro
    UI->>V: GET /carros/<id>/
    V->>DB: Consulta plantilla canónica y faltantes
    V->>DB: Selecciona Lote FEFO de Bodega
    QF->>UI: Confirma entrega de ampollas e ingresa nuevo precinto (PREC-2026-X)
    UI->>V: POST /carros/<id>/reponer/
    V->>DB: Descuenta stock de Lote en Bodega
    V->>DB: Repone cantidad_actual en PlantillaItemCarro
    V->>DB: Registra ReposicionCarro con número de precinto
    V->>DB: Cambia estado a "Completo - Operativo"
    V->>MDB: Bitácora de reposición y precintado
    V-->>UI: Carro de Paro 100% operativo y sellado
```

---

### 2.4 Vista de Desarrollo (Estructura de Módulos Django)

```mermaid
flowchart TD
    subgraph DjangoProject["cesfam_farmacia_web (Django 6.x)"]
        CONFIG["config (settings, urls, wsgi, asgi)"]
        
        subgraph Apps["Aplicaciones Modulares"]
            CORE["core (Autenticación, RBAC, Pacientes, Utils, Fallback)"]
            FARM["farmacia (Medicamentos, Lotes FEFO, Bodega/Vitrina)"]
            DISP["dispensacion (Recetas, Dispensación $0, Tercero)"]
            GES["ges (Patologías, Canastas, Saldo Cuotas)"]
            CTRL["controlados (Libro Foliado D.S. 404/405, 2FA)"]
            CARR["carros_clinicos (Carro Paro, Unidosis, Precintos)"]
            REPO["reportes (PDF, Excel, Métricas Chart.js)"]
            API["api (REST API, Serializers, DRF ViewSets)"]
        end
    end

    CONFIG --> Apps
    CORE --> FARM
    FARM --> DISP
    CORE --> DISP
    GES --> DISP
    FARM --> CTRL
    FARM --> CARR
    Apps --> REPO
    Apps --> API
```

---

### 2.5 Vista Física / Despliegue (Arquitectura Híbrida)

```mermaid
flowchart LR
    subgraph Clientes["Terminales de Atención"]
        PC["PC de Farmacia Mostrador (Windows/Edge)"]
        TAB["Tablet Box de Reanimación (Android/Chrome)"]
        ADM_PC["Estación de Administración (Windows/Firefox)"]
    end

    subgraph Servidor["Servidor de Aplicación (Local / Servidor CESFAM)"]
        WEB["Servidor Web (Nginx / WhiteNoise)"]
        APP["Backend Django 6.x / Gunicorn (Python 3.14)"]
        
        subgraph MotoresBD["Arquitectura Híbrida de Bases de Datos"]
            PG["PostgreSQL 18 (Relacional)<br/>Base: cesfam_farmacia_db<br/>Port: 5432<br/>(Transacciones ACID, PK/FK)"]
            MG["MongoDB 9.0 (NoSQL)<br/>Base: cesfam_nosql_db<br/>Port: 27017<br/>(Auditoría Append-Only, FHIR, Alertas)"]
            FALL["Fallback Documental Local JSON<br/>(Resiliencia si MongoDB no responde)"]
        end
    end

    Clientes -->|HTTPS / TLS 1.3| WEB
    WEB --> APP
    APP -->|psycopg2 / SQL Parametrizado| PG
    APP -->|pymongo / BSON| MG
    APP -.->|Fallback transparente| FALL
```
