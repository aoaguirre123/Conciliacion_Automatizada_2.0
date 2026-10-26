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
- [Estado Actual del Desarrollo](#estado-actual)
- [Puesta en Marcha](#puesta-en-marcha)
- [Gestión de Usuarios](#usuarios)
- [Estructura del Proyecto](#estructura)
- [Metodología de Trabajo](#metodologia)
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

- **Frontend:** Plantillas HTML de Django, CSS y JavaScript (interfaz web responsive)
- **Backend:** Python 3.12 / Django 5.1+ (motor de conciliación y vistas)
- **Base de Datos:** SQLite
- **Procesamiento de Archivos:** Pandas, OpenPyXL (`.xlsx`), xlrd (`.xls`), lxml (`.xls` exportados como página web) y odfpy (`.ods`)
- **Servicios Externos:** httpx para el dólar observado (mindicador.cl)
- **Herramientas:** Git / GitHub
- **Despliegue:** Servidor del CITT (aplicación web, sin instalación en los equipos del hotel)

> ℹ️ **Cambio respecto al diseño inicial:** la Fase 1 contemplaba Angular + Django REST Framework + PostgreSQL / SQL Server. Para entregar una primera versión funcional dentro del semestre se optó por una aplicación Django con plantillas y SQLite: un solo proyecto, más simple de instalar en el servidor del CITT. La lógica de conciliación está separada de las vistas, por lo que una API o una base de datos distinta pueden incorporarse más adelante.

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
* **Capa de Persistencia:** Base de datos **SQLite** gestionada con el ORM de Django (usuarios, historial de conciliaciones, reportes Excel y base de BIN).
* **Despliegue:** Aplicación web instalada en el **servidor del CITT**; los usuarios acceden desde el navegador.
---
<a id="estado-actual" name="estado-actual"></a>
## 🚦 Estado Actual del Desarrollo

La versión vigente del sistema es **Conciliación bancaria**, desarrollada como aplicación web Django con plantillas HTML y base de datos SQLite. El código se encuentra en la carpeta `Conciliacion_Bancaria_2.0/`, en la raíz del repositorio.

#### Módulos Disponibles
* **Conciliación en Dólares (USD):** Cruce entre ERP, Transbank, cartolas de las marcas internacionales (**Amex, Diners, Visa y Mastercard**) y banco, utilizando el dólar observado obtenido desde **mindicador.cl**.
* **Conciliación en Pesos (CLP):** Cruce de los abonos de Transbank (**crédito, débito y prepago**) contra los pagos con tarjeta del **BORDERO**, con verificación del abono en la cartola bancaria.
* **Historial:** Registro de todas las conciliaciones guardadas, con su resultado y los reportes Excel descargables.
* **Identificación de Tarjetas:** En la conciliación en pesos, cada venta se identifica por los **6 primeros dígitos (BIN)** de la tarjeta: **marca, tipo (crédito, débito o prepago), banco emisor y país**. Se muestra en el resultado y en los Excel, sin depender de internet.

#### Tecnologías Utilizadas
* **Framework:** Django 5.1+ (plantillas HTML, CSS y JavaScript)
* **Base de Datos:** SQLite
* **Procesamiento de Archivos:** Pandas, OpenPyXL, xlrd, lxml y odfpy (`.xlsx`, `.xls`, `.ods`, CSV y `.xls` exportados como página web; el formato se detecta por contenido)
* **Servicios Externos:** httpx para consultar el dólar observado en mindicador.cl
* **Datos de BIN:** [bin-list-data](https://github.com/venelinkochev/bin-list-data) (licencia **CC-BY-4.0**), incluida en el proyecto y cargada en la base de datos con `migrate`

---
<a id="puesta-en-marcha" name="puesta-en-marcha"></a>
## 🚀 Puesta en Marcha

#### Requisitos
* **Python 3.12** o superior
* **Git**

#### Instalación en Windows
Abrir una terminal en la raíz del repositorio clonado y ejecutar:

```
cd Conciliacion_Bancaria_2.0
python -m venv entorno
entorno\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Luego abrir **http://127.0.0.1:8000/** e ingresar con el correo y la contraseña del usuario.

> 💳 **Base de BIN:** la primera vez, `migrate` también carga la base de tarjetas (~375.000 BIN), por lo que demora un poco más.

> 🍎 **macOS / Linux:** activar el entorno con `source entorno/bin/activate`.

---
<a id="usuarios" name="usuarios"></a>
## 👤 Gestión de Usuarios

* **Base de datos:** `db.sqlite3` incluye solo un usuario de prueba; las conciliaciones de cada equipo no se suben al repositorio.
* **Inicio de sesión por correo:** el login solicita **correo electrónico**, por lo que cada usuario debe tener un correo registrado.
* **Creación de usuarios:**
  * Desde la terminal con `python manage.py createsuperuser`.
  * Desde la opción **"Usuarios y permisos"** del menú (disponible solo para usuarios *staff*).

---
<a id="estructura" name="estructura"></a>
## 📁 Estructura del Proyecto

```
Conciliacion_Bancaria_2.0/
├── config/                    configuración de Django
├── apps/
│   ├── core/                  pantalla de inicio
│   ├── usuarios/              login y cierre de sesión
│   └── conciliacion/
│       ├── logica.py          conciliación en dólares y sus Excel
│       ├── logica_clp.py      conciliación en pesos contra el BORDERO y sus Excel
│       ├── models.py          historial (Conciliacion, Reporte) y BIN de tarjetas (BinTarjeta)
│       ├── registro.py        guarda cada conciliación en el historial
│       ├── dolar.py           dólar observado (mindicador.cl)
│       ├── bines.py           identificación de tarjetas por BIN
│       ├── datos/             bines.csv.gz (base de BIN) y preparar_bines.py (para actualizarla)
│       └── views.py           pantallas, historial y descargas
├── templates/                 HTML
├── static/
│   ├── css/app.css            hoja de estilos única
│   └── js/                    app.js (menú) y conciliacion.js (carga de archivos)
├── manage.py
└── requirements.txt
```

---
<a id="metodologia" name="metodologia"></a>
## 🔄 Metodología de Trabajo

Para la ejecución del proyecto se utiliza una **metodología ágil adaptada (Scrum)**, organizada en iteraciones o **Sprints de 2 semanas**. Este marco de trabajo facilita la realización de entregas incrementales y funcionales del producto, permitiendo la revisión continua junto al cliente y garantizando una alta capacidad de adaptación frente a ajustes en las reglas de conciliación bancaria o variaciones en las estructuras de los archivos de entrada.


###  Fases del Proyecto

####  Fase 1: Levantamiento y Análisis
* **Objetivo:** Extracción y formalización de las reglas del motor de conciliación.
* **Actividades:**
  * Realización de entrevistas con los actores clave del proceso.
  * Análisis detallado de planillas y cartolas bancarias reales del **Hotel Plaza San Francisco**.
  * Definición de casos de borde y patrones de discrepancia habituales.

####  Fase 2: Diseño y Arquitectura
* **Objetivo:** Definición de la estructura de datos, componentes de software y experiencia de usuario.
* **Actividades:**
  * Modelado de la Base de Datos con el ORM de **Django** (SQLite).
  * Diseño y prototipado UI/UX de la interfaz web con plantillas de **Django**.
  * Definición de la arquitectura por capas: lectura de archivos, motores de conciliación, vistas y persistencia.

####  Fase 3: Desarrollo Incremental
* **Objetivo:** Implementación iterativa de los componentes centrales de la plataforma.
* **Actividades:**
  * **Módulo de Ingesta:** Lectura, validación y parseo de los 6 Excels nativos.
  * **Motor de Conciliación:** Desarrollo del algoritmo *3-Way Match* bancario y motor de tarjetas (CLP / USD).
  * **Módulo de Discrepancias:** Gestión y clasificación de inconsistencias.
  * **Dashboards:** Visualización gráfica de métricas y reportes ejecutivos.

####  Fase 4: Pruebas y Control de Calidad (QA)
* **Objetivo:** Asegurar la consistencia, seguridad e integridad financiera de los cálculos.
* **Actividades:**
  * Pruebas automatizadas de Django con datos sintéticos (lectura de archivos, motores CLP / USD y pantallas).
  * Pruebas de **precisión algorítmica** utilizando volúmenes de datos reales para garantizar la exactitud en el cruce de transacciones.

####  Fase 5: Despliegue y Documentación
* **Objetivo:** Puesta en producción y entrega formal de la solución.
* **Actividades:**
  * Instalación y puesta en marcha en el **servidor del CITT**.
  * Elaboración del manual de usuario para el equipo operativo (Tesorería, Contabilidad, Auditoría).
  * Documentación técnica del repositorio y finalización del proyecto.
