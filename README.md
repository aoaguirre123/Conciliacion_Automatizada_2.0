# Conciliación Automatizada 2.0 | Hotel Plaza San Francisco

Sistema web de automatización de conciliaciones contables y bancarias desarrollado para el **Hotel Plaza San Francisco** en el marco de la asignatura Capstone (PTY4614) de Duoc UC (Sede Padre Alonso de Ovalle).

---
<a id="informacion-del-proyecto" name="informacion-del-proyecto"></a>
## 📋 Información del Proyecto

- **Proyecto:** Conciliación Automatizada 2.0 (Tarjetas CLP/USD + 3-Way Match Bancario)
- **Cliente / Organización:** Hotel Plaza San Francisco (Santiago, Chile)
- **Institución:** Duoc UC — Escuela de Informática y Telecomunicaciones
- **Carrera:** Ingeniería en Informática

---
<a id="integrantes-del-equipo" name="integrantes-del-equipo"></a>
## 👥 Integrantes del Equipo

| Nombre Integrante | RUT | Correo Institucional | Rol en el Proyecto |
| :--- | :--- | :--- | :--- |
| **Jesús Antonio Márquez Bahamonde** | 21.038.733-1 | `jesu.marquez@duocuc.cl` | Desarrollador Full-Stack |
| **Aoris Alejandro Aguirre Sanchez** | 21.778.698-3 | `ao.aguirre@duocuc.cl` | Líder de Proyecto & Analista |
| **Victor Faviano Yañez Naranjo** | 21.805.703-9 | `vi.yanezn@duocuc.cl` | Arquitecto de Software |

---

<a id="tabla-de-contenidos" name="tabla-de-contenidos"></a>
## 📋 Tabla de Contenidos
- [Información del Proyecto](#informacion-del-proyecto)
- [Integrantes del Equipo](#integrantes-del-equipo)
- [Tabla de Contenidos](#tabla-de-contenidos)
- [Enlaces Oficiales](#enlaces-oficiales)
- [Descripción y Alcance de la Solución](#descripcion-y-alcance)
- [Stack Tecnológico](#stack-tecnologico) 
- [Arquitectura del Sistema](#arquitectura)

---
<a id="enlaces-oficiales" name="enlaces-oficiales"></a>
## 🔗 Enlaces Oficiales

- **Repositorio GitHub (Público):** [https://github.com/aoaguirre123/Conciliacion_Automatizada_2.0.git](https://github.com/aoaguirre123/Conciliacion_Automatizada_2.0.git)
- **Carpeta Compartida Google Drive:** [https://drive.google.com/drive/folders/1r__3r5JleDGuKB9gFdndDaJGxt7evbvC?usp=sharing](https://drive.google.com/drive/folders/1r__3r5JleDGuKB9gFdndDaJGxt7evbvC?usp=sharing)

---
<a id="descripcion-y-alcance" name="descripcion-y-alcance"></a>
## 🎯 Descripción y Alcance de la Solución

El proyecto reemplaza el procedimiento manual de revisión línea por línea (que tomaba entre 2 y 4 horas diarias) mediante una plataforma web desacoplada que procesa **6 archivos Excel nativos** sin modificación previa:

1. **Ingesta Masiva de Archivos Nativos:** Carga directa de planillas descargadas de Transbank (Débito, Crédito CLP/USD y Prepago), ERP CM SFM (Borderó) y Banco (Cartola / Control Financiero).
2. **Motor de Conciliación de Tarjetas (CLP / USD):**
   - **Pesos (CLP):** Calce algorítmico por llave `Código Autorización Transbank = Número Documento ERP` con margen de tolerancia configurable de **$500 a $1.000 CLP**.
   - **Dólares (USD):** Conciliación aislando variaciones generadas por la fluctuación del tipo de cambio en transacciones de huéspedes extranjeros.
3. **Conciliación Bancaria 3-Way Match:** Validación tripartita (*Cartola Bancaria vs. Control Financiero Interno vs. Contabilidad ERP*) evaluando Fecha, Monto y Glosa para lograr cuadratura absoluta (Diferencia = 0).
4. **Módulo de Reporte de Excepciones:** Clasificación automática de errores de tipeo humano (`'0'` por `'O'`), cuotas diferidas, notas de crédito/anulaciones y registros borrados en contabilidad.
5. **Dashboard Ejecutivo:** Visualización interactiva en tiempo real con indicadores KPI de saldos conciliados vs. partidas pendientes de revisión.

---
<a id="stack-tecnologico" name="stack-tecnologico"></a>
## 🛠️ Stack Tecnológico

- **Frontend:** Angular SPA (Interfaz web responsive e intuitiva)
- **Backend:** Python 3.12 / Django REST Framework (Motor de procesamiento algorítmico)
- **Base de Datos:** PostgreSQL / SQL Server
- **Bibliotecas y Herramientas:** Pandas, OpenPyXL, ReportLab, Graphviz, Git/GitHub
- **Despliegue:** Servidor Local / Entorno Cloud (GCP / Azure)

---
<a id="arquitectura" name="arquitectura"></a>
## 📐 Arquitectura del Sistema

**Estilo Arquitectónico: Arquitectura por Capas (N-Tier) orientada a un Pipeline de Procesamiento Batch con Motor de Reglas (3-Way Match).**
El flujo de trabajo y la arquitectura general de la **Plataforma Conciliación 2.0** se estructuran en 4 capas principales:

#### 1. Usuarios
Diseñado para la interacción de las áreas operativas y de control:
* **Tesorería**
* **Contabilidad**
* **Auditoría**

#### 2. Insumos
El sistema soporta la **carga directa** de 6 archivos Excel nativos provenientes de las distintas fuentes operativas:
* **Transbank** (Comprobantes y liquidaciones)
* **ERP CM SFM** (Registros contables)
* **Cartola Bancaria** (Extractos bancarios)
* **Control Interno** (Archivos auxiliares de validación)

#### 3. Plataforma Conciliación 2.0 (Core)
Módulo central encargado del procesamiento, lógica de negocio y presentación de datos:
* **Ingesta de Archivos:** Recibe, valida y parsea los archivos cargados por los usuarios antes de su procesamiento.
* **Motor Bancario 3-Way Match:** Ejecuta el algoritmo de conciliación tripartita para validar los movimientos bancarios frente a los registros contables y de control.
* **Motor Conciliación Tarjetas (CLP / USD):** Procesa y concilia transacciones operadas con tarjeta de crédito/débito tanto en moneda local (CLP) como extranjera (USD).
* **Reporte de Excepciones & Dashboard:** Módulo de visualización y salida que consolida los resultados de ambos motores, exponiendo un panel con métricas clave y la lista detallada de discrepancias/excepciones.

#### 4. Base de Datos e Infraestructura
* **Capa de Persistencia:** Gestión de datos estructurados mediante **PostgreSQL** o **SQL Server**.
* **Despliegue:** Flexible para integrarse tanto en un **Servidor Local (On-Premise)** como en entornos **Cloud**.
