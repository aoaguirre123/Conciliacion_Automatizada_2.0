# Conciliación Automatizada 2.0 | Hotel Plaza San Francisco

Sistema web de automatización de conciliaciones contables y bancarias desarrollado para el **Hotel Plaza San Francisco** en el marco de la asignatura Capstone (PTY4614) de Duoc UC (Sede Padre Alonso de Ovalle).

---
<a id="informacion-del-proyecto" name="informacion-del-proyecto"></a>
## 📋 Información del Proyecto

- **Proyecto:** Conciliación Automatizada 2.0 (conciliación de tarjetas en CLP y USD; el 3-Way Match bancario quedó fuera del alcance del semestre)
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
- [Innovación y Propuesta de Valor](#innovacion)
- [Stack Tecnológico](#stack-tecnologico) 
- [Arquitectura del Sistema](#arquitectura)
- [Estado Actual del Desarrollo](#estado-actual)
- [Puesta en Marcha](#puesta-en-marcha)
- [Gestión de Usuarios](#usuarios)
- [Estructura del Proyecto](#estructura)
- [Metodología de Trabajo](#metodologia)
- [Documentación del Proyecto](#documentacion)
---
<a id="enlaces-oficiales" name="enlaces-oficiales"></a>
## 🔗 Enlaces Oficiales

- **Repositorio GitHub (Público):** [https://github.com/aoaguirre123/Conciliacion_Automatizada_2.0.git](https://github.com/aoaguirre123/Conciliacion_Automatizada_2.0.git)
- **Evidencias de la Fase 2:** carpeta [`Fase 2`](Fase%202) de este repositorio (ver [Documentación del Proyecto](#documentacion)).
- **Carpeta Compartida Google Drive:** [https://drive.google.com/drive/folders/1r__3r5JleDGuKB9gFdndDaJGxt7evbvC?usp=sharing](https://drive.google.com/drive/folders/1r__3r5JleDGuKB9gFdndDaJGxt7evbvC?usp=sharing)

---
<a id="descripcion-y-alcance" name="descripcion-y-alcance"></a>
## 🎯 Descripción y Alcance de la Solución

El proyecto reemplaza el procedimiento manual de revisión línea por línea (que tomaba entre 2 y 4 horas diarias) mediante una plataforma web que procesa los **archivos Excel tal como se descargan**, sin modificación previa. El alcance definido con el cliente es el siguiente (lo ya implementado se detalla en [Estado Actual del Desarrollo](#estado-actual)):

1. **Ingesta Masiva de Archivos Nativos:** Carga directa de planillas descargadas de Transbank (Débito, Crédito CLP/USD y Prepago), ERP CM SFM (Borderó) y Banco (Cartola / Control Financiero).
2. **Motor de Conciliación de Tarjetas (CLP / USD):**
   - **Pesos (CLP):** Calce algorítmico por llave `Código Autorización Transbank = Número Documento ERP` con margen de tolerancia configurable de **$500 a $1.000 CLP**.
   - **Dólares (USD):** Conciliación aislando variaciones generadas por la fluctuación del tipo de cambio en transacciones de huéspedes extranjeros.
3. **Conciliación Bancaria 3-Way Match:** *fuera del alcance del semestre por decisión del docente* (el hotel tiene muchas cuentas, en distintos bancos y con formatos propios). Se mantiene la verificación del abono de Transbank en la cartola.
4. **Módulo de Reporte de Excepciones:** Clasificación automática de errores de tipeo humano (`'0'` por `'O'`), cuotas diferidas, notas de crédito/anulaciones y registros borrados en contabilidad.
5. **Dashboard de cuadratura:** indicadores y gráficos en cada conciliación («Dónde mirar primero») con lo conciliado y lo pendiente de revisión.

---
<a id="innovacion" name="innovacion"></a>
## 💡 Innovación y Propuesta de Valor

**Qué problema resuelve.** Tesorería del hotel cruzaba a mano, línea por línea y en planillas Excel, los abonos de Transbank, los pagos registrados en el BORDERO y las cartolas de los bancos, en pesos y en dólares. Eso tomaba entre 2 y 4 horas diarias, con alto riesgo de error y descuadres que se detectaban tarde.

**Qué lo hace diferente.**
* **Lee los archivos tal como se descargan:** reconoce cada Excel por su contenido (columnas y encabezados), no por su nombre, incluso formatos antiguos o exportados como página web. El usuario no ordena ni modifica nada.
* **Cruce por prioridades que entiende los errores reales:** primero el código de autorización y el monto exactos; luego códigos mal digitados (por ejemplo `O` por `0`); luego monto y fecha dentro de una ventana de días. Así no marca como faltante una venta que sí está registrada con un error.
* **Identificación de tarjetas sin internet:** marca, tipo y banco emisor de cada venta a partir del BIN, con una base local de unos 375.000 BIN.
* **Excepciones con acción sugerida:** cada diferencia queda clasificada en uno de nueve tipos, con qué hacer y su seguimiento (pendiente, en revisión, resuelta), en vez de una lista de diferencias sin contexto.
* **Dónde mirar primero:** cada conciliación indica con frases y gráficos por dónde empezar a revisar.

**Qué valor agrega.**
* Procesa en segundos lo que antes tomaba horas: unas 10.500 ventas en 8,3 segundos.
* Con archivos reales, concilió automáticamente 103 de 141 ventas; el analista se concentra en las excepciones.
* Deja trazabilidad para Contabilidad y Auditoría: cada conciliación, sus reportes y la gestión de cada excepción quedan guardados con usuario y fecha.
* Funciona desde el navegador, sin instalar software en los equipos del hotel.

---
<a id="stack-tecnologico" name="stack-tecnologico"></a>
## 🛠️ Stack Tecnológico

- **Frontend:** Plantillas HTML de Django, CSS y JavaScript (interfaz web responsive)
- **Backend:** Python 3.13 / Django 5.2 (motor de conciliación y vistas)
- **Base de Datos:** SQLite
- **Procesamiento de Archivos:** Pandas, OpenPyXL (`.xlsx`), xlrd (`.xls`), lxml (`.xls` exportados como página web) y odfpy (`.ods`)
- **Reportes PDF:** ReportLab
- **Servicios Externos:** httpx para el dólar observado (mindicador.cl, findic.cl y, con API key, la API de la CMF)
- **Herramientas:** Git / GitHub
- **Contenedores:** Docker y Docker Compose (alternativa para levantar la aplicación)
- **Despliegue:** PythonAnywhere, con WhiteNoise para los archivos estáticos (aplicación web, sin instalación en los equipos del hotel)

> ℹ️ **Cambio respecto al diseño inicial:** la Fase 1 contemplaba Angular + Django REST Framework + PostgreSQL / SQL Server. Para entregar una primera versión funcional dentro del semestre se optó por una aplicación Django con plantillas y SQLite: un solo proyecto, más simple de instalar y publicar (PythonAnywhere). La lógica de conciliación está separada de las vistas, por lo que una API o una base de datos distinta pueden incorporarse más adelante.

---
<a id="arquitectura" name="arquitectura"></a>
## 📐 Arquitectura del Sistema

**Estilo Arquitectónico: Aplicación web por capas sobre el patrón MVT de Django (Modelo–Vista–Plantilla), con procesamiento por lotes de los archivos cargados.**
La lógica de conciliación vive en módulos independientes de las vistas (`lectura.py`, `logica.py`, `logica_clp.py`), lo que permite probarla por separado y reutilizarla. El flujo de trabajo se estructura en 4 capas principales:

#### 1. Usuarios
Diseñado para la interacción de las áreas operativas y de control:
* **Analista de Tesorería:** concilia y gestiona las excepciones.
* **Contador / Auditor:** consulta el historial, el detalle y los reportes.
* **Administrador:** todo lo anterior, más la configuración y los usuarios.

#### 2. Insumos
El sistema soporta la **carga directa** de los archivos Excel nativos de cada fuente operativa:
* **Transbank:** reporte «Abonos por día» en pesos y en dólares (crédito, débito y prepago, en uno o varios archivos) y la liquidación en dólares del formato anterior.
* **ERP CM SFM:** BORDERO de débitos y créditos del FrontOffice y cuentas por cobrar de tarjetas en dólares (Amex, Diners, Visa y Mastercard).
* **Cartola Bancaria:** BancoEstado (pesos) y Banco de Chile (pesos y dólares).

#### 3. Plataforma Conciliación 2.0 (Core)
Módulo central encargado del procesamiento, lógica de negocio y presentación de datos:
* **Ingesta de Archivos:** Recibe, valida y parsea los archivos cargados por los usuarios antes de su procesamiento.
* **Motor Conciliación Tarjetas (CLP / USD):** Procesa y concilia transacciones operadas con tarjeta de crédito, débito y prepago tanto en moneda local (CLP) como extranjera (USD).
* **Excepciones:** clasificación de cada diferencia con una acción sugerida, gestión por estado y reporte en PDF o Excel.
* **Motor Bancario 3-Way Match:** *fuera del alcance del semestre.*
* **Resultados, Excepciones e Historial:** Pantalla de resultados con indicadores y detalle de discrepancias, reportes Excel descargables e historial de todas las conciliaciones realizadas.

#### 4. Base de Datos e Infraestructura
* **Capa de Persistencia:** Base de datos **SQLite** gestionada con el ORM de Django (usuarios, historial de conciliaciones, reportes Excel y base de BIN).
* **Despliegue:** Aplicación web publicada en **PythonAnywhere**, con la base de datos fuera del repositorio; los usuarios acceden desde el navegador. Pasos en [`DESPLIEGUE_PYTHONANYWHERE.md`](DESPLIEGUE_PYTHONANYWHERE.md).
---
<a id="estado-actual" name="estado-actual"></a>
## 🚦 Estado Actual del Desarrollo

La versión vigente del sistema es **Conciliación bancaria v3.14.0**, desarrollada como aplicación web Django con plantillas HTML y base de datos SQLite. El código se encuentra en la carpeta `Conciliacion_Bancaria_2.0/`, en la raíz del repositorio.

#### Módulos Disponibles
* **Conciliación en Pesos (CLP):** Cruce de los abonos de Transbank (**crédito, débito y prepago**, en uno o varios archivos) contra los pagos con tarjeta del **BORDERO** por código de autorización y monto, con verificación del abono en la cartola de **BancoEstado** o **Banco de Chile**. Detecta diferencias de monto, ventas sin registro, ventas fuera del período, errores de digitación del código y datos duplicados. Reconoce las **ventas en cuotas**: cada venta se cruza una sola vez con el BORDERO y se informan las cuotas que no vienen en los reportes cargados, con el mes en que se esperaban, para volver a conciliar con un período más amplio. Al soltar los archivos muestra qué fechas de venta trae cada reporte de Transbank, y los **pagos del BORDERO sin abono** se limitan a esas fechas (crédito y débito por separado), indicando cuántos pagos de otras fechas se omitieron.
* **Conciliación en Dólares (USD):** Cruce entre Transbank, el BORDERO (ERP), las cuentas por cobrar de **Amex, Diners, Visa y Mastercard** y la cartola en dólares de **Banco de Chile**. Muestra como referencia el dólar observado del día (**mindicador.cl**, con respaldo en **findic.cl** y en la **API de la CMF** si se configura `CMF_API_KEY`; si ninguna responde, muestra el último valor obtenido).
* **Historial:** Registro de todas las conciliaciones guardadas, con su resultado y los reportes Excel descargables.
* **Identificación de Tarjetas:** Cada venta se identifica por los **6 primeros dígitos (BIN)** de la tarjeta: **marca, tipo (crédito, débito o prepago), banco emisor y país**, sin depender de internet. En dólares se usa para saber la marca de cada venta.
* **Gestión de excepciones:** Cada caso por revisar se clasifica (error de digitación, diferencia de monto, venta sin registro, anulación, cuota diferida, etc.) con una acción sugerida; el analista lo marca en revisión o resuelto, comenta y puede reclasificarlo.
* **Reporte de excepciones:** Exportación en PDF ejecutivo o Excel, de una conciliación o de todas, con código, monto, estado y acción sugerida.
* **Dónde mirar primero:** Cada conciliación muestra un resumen gráfico con frases que indican por dónde empezar, cómo quedaron las ventas, el monto por revisar por medio de pago o marca y por día de venta, y las ventas con más monto por revisar.
* **Configuración:** Pantalla para administradores donde se ajustan la **tolerancia de montos** en pesos (hasta $1.000) y en dólares (hasta US$ 5), la **ventana de días** entre la venta y el pago, y las **palabras clave** que identifican los abonos de Transbank en la cartola. Los valores fuera de rango se rechazan y cada conciliación guarda los criterios con que se hizo.
* **Usuarios y perfiles:** Inicio de sesión por correo; todas las pantallas requieren sesión. Tres perfiles: **Administrador**, **Analista de Tesorería** y **Contador / Auditor**, administrados desde la pantalla **Usuarios**.
* **Vista previa:** al cargar los archivos se muestra lo que se leyó de cada uno (período, filas, totales y primeras filas) antes de conciliar.

#### Fuera del alcance y trabajo futuro
* Conciliación bancaria 3-Way Match (fuera del alcance del semestre por decisión del docente).
* Panel consolidado con indicadores acumulados de varias conciliaciones.
* Arrastre de movimientos pendientes entre conciliaciones.
* Operación de los tres recintos de la cadena.
* Dos defectos abiertos registrados en el plan de pruebas (DEF-08 y DEF-09).

#### Tecnologías Utilizadas
* **Framework:** Django 5.2 (plantillas HTML, CSS y JavaScript)
* **Base de Datos:** SQLite
* **Procesamiento de Archivos:** Pandas, OpenPyXL, xlrd, lxml y odfpy (`.xlsx`, `.xls`, `.ods`, CSV y `.xls` exportados como página web; el formato se detecta por contenido)
* **Servicios Externos:** httpx para consultar el dólar observado en mindicador.cl, findic.cl y la API de la CMF
* **Datos de BIN:** [bin-list-data](https://github.com/venelinkochev/bin-list-data) (licencia **CC-BY-4.0**), incluida en el proyecto y cargada en la base de datos con `migrate`

---
<a id="puesta-en-marcha" name="puesta-en-marcha"></a>
## 🚀 Puesta en Marcha

#### Requisitos
* **Python 3.12** o superior (probado con 3.13)
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

Luego abrir **http://127.0.0.1:8000/** e ingresar con uno de los usuarios de demostración incluidos en `db.sqlite3` (contraseña `Prueba-2026-x`):

| Correo | Perfil |
| :--- | :--- |
| `admin@hoteldemo.cl` | Administrador |
| `tesoreria@hoteldemo.cl` | Analista de Tesorería |
| `contabilidad@hoteldemo.cl` | Contador / Auditor |

Con el administrador se puede usar **Conciliar con archivos de ejemplo** en las pantallas En pesos y En dólares.

> 💳 **Base de BIN:** si se parte sin `db.sqlite3`, `migrate` crea la base y carga las tarjetas (~375.000 BIN), por lo que demora un poco más.

> ✅ **Pruebas automáticas:** `python manage.py test apps` ejecuta las 212 pruebas con datos sintéticos.

> 🔒 **Datos:** el repositorio no contiene datos reales del hotel. `db.sqlite3` y los archivos de `ejemplos/` son ficticios y solo sirven para probar; para el uso real se parte con una base vacía fuera del repositorio (ver [`DESPLIEGUE_PYTHONANYWHERE.md`](DESPLIEGUE_PYTHONANYWHERE.md)).

> 🍎 **macOS / Linux:** activar el entorno con `source entorno/bin/activate`.

#### Con Docker

Con [Docker](https://www.docker.com/) instalado, desde la raíz del repositorio:
```
docker compose up --build
```
Luego abrir **http://localhost:8000/**. El contenedor usa una base de datos **vacía**, guardada en el volumen `datos` (no la base de demostración), y la primera vez carga la base de BIN, por lo que demora un poco. Se crea un administrador con el correo y la contraseña de las variables `ADMIN_EMAIL` y `ADMIN_PASSWORD` (por defecto `admin@hotel.cl` / `Cambiar-2026`). Para usar otros valores y una clave secreta propia, copiar `.env.example` como `.env` (junto a `docker-compose.yml`) y cambiar sus valores:
```
DJANGO_SECRET_KEY=una-clave-larga-y-privada
ADMIN_EMAIL=ti@hotel.cl
ADMIN_PASSWORD=una-contraseña-segura
CMF_API_KEY=
```
`CMF_API_KEY` es opcional: con una API key de la CMF (gratuita, en https://api.cmfchile.cl) se suma esa fuente para el dólar observado.
| Archivo | Para qué sirve |
| :--- | :--- |
| `Conciliacion_Bancaria_2.0/Dockerfile` | Imagen con Python 3.13, las dependencias y gunicorn; al iniciar aplica las migraciones y crea el administrador. |
| `Conciliacion_Bancaria_2.0/.dockerignore` | Deja fuera de la imagen el entorno virtual, la base local y los archivos temporales. |
| `docker-compose.yml` | Levanta la aplicación en el puerto 8000 con sus variables de entorno y el volumen de datos. |
| `.env.example` | Variables de entorno de ejemplo: clave secreta y primer administrador. |

Para detenerla: `docker compose down` (los datos se conservan en el volumen).

---
<a id="usuarios" name="usuarios"></a>
## 👤 Gestión de Usuarios

* **Base de datos:** `db.sqlite3` incluye solo los tres usuarios de demostración y la base de BIN; las conciliaciones no se suben al repositorio.
* **Inicio de sesión por correo:** el login solicita **correo electrónico**, por lo que cada usuario debe tener un correo registrado.
* **Perfiles:**

  | Acción | Administrador | Analista de Tesorería | Contador / Auditor |
  |---|:---:|:---:|:---:|
  | Conciliar en pesos y dólares | ✓ | ✓ | – |
  | Ver historial, detalle y descargar reportes | ✓ | ✓ | ✓ |
  | Conciliar con archivos de ejemplo | ✓ | – | – |
  | Borrar conciliaciones del historial | ✓ | – | – |
  | Configuración y usuarios | ✓ | – | – |

* **Creación de usuarios:** desde **Administración › Usuarios** (solo administradores): nombre, correo, perfil y contraseña inicial. Desde ahí también se cambia el perfil, se desactiva una cuenta o se cambia su contraseña. Los administradores solo los crea, modifica o desactiva el **superusuario** (creado con `python manage.py createsuperuser`); un administrador crea y edita Analistas y Contadores.

---
<a id="estructura" name="estructura"></a>
## 📁 Estructura del Proyecto

```
Conciliacion_Automatizada_2.0/
├── Conciliacion_Bancaria_2.0/     aplicación Django (detalle abajo)
├── Fase 1/                        evidencias individuales y grupales de la Fase 1
├── Fase 2/                        evidencias de la Fase 2 (ver Documentación del Proyecto)
├── DESPLIEGUE_PYTHONANYWHERE.md   publicación en PythonAnywhere
├── docker-compose.yml             levantar la aplicación con Docker
├── .env.example                   variables de entorno de ejemplo para Docker
└── README.md

Conciliacion_Bancaria_2.0/
├── config/                    configuración de Django (settings, urls)
│   └── formatos/es_CL/        formato chileno de números (miles con punto, decimales con coma)
├── apps/
│   ├── core/                  pantalla de inicio
│   ├── usuarios/              login, perfiles (perfiles.py) y administración de usuarios
│   └── conciliacion/
│       ├── lectura.py         lectura de archivos (.xls, .xlsx, .ods, CSV y HTML) detectando el formato
│       ├── vista_previa.py    lo que se leyó de cada archivo antes de conciliar
│       ├── logica.py          conciliación en dólares y sus Excel
│       ├── logica_clp.py      conciliación en pesos contra el BORDERO y sus Excel
│       ├── excepciones.py     clasificación de excepciones y acción sugerida
│       ├── reporte_excepciones.py  reporte de excepciones en PDF y Excel
│       ├── pdf_base.py, pdf_documentos.py  documentos de cada conciliación en PDF
│       ├── graficos.py        «Dónde mirar primero» (indicadores y gráficos)
│       ├── models.py          Conciliacion, Reporte, Excepcion, Configuracion y BinTarjeta
│       ├── parametros.py      tolerancias, ventana de días y palabras clave de la cartola (valores por defecto)
│       ├── forms.py           formulario de la pantalla de configuración
│       ├── registro.py        guarda cada conciliación en el historial
│       ├── dolar.py           dólar observado (mindicador.cl, findic.cl y CMF)
│       ├── bines.py           identificación de tarjetas por BIN
│       ├── views.py           pantallas, historial y descargas
│       ├── tests.py           pruebas automáticas con datos sintéticos
│       ├── migrations/        tablas de la base de datos y carga inicial de BIN
│       └── datos/             bines.csv.gz (base de BIN) y preparar_bines.py (para actualizarla)
├── templates/                 HTML (base, menú, login, inicio, conciliación, excepciones y usuarios)
├── static/
│   ├── css/app.css            hoja de estilos única (modo día y modo noche)
│   ├── js/                    menú, carga de archivos, progreso, excepciones, gráficos e historial
│   └── img/                   logo y fondo del login
├── ejemplos/                  archivos ficticios para «Conciliar con archivos de ejemplo»
├── db.sqlite3                 base de demostración (usuarios de prueba y BIN)
├── Dockerfile                 imagen Docker de la aplicación
├── manage.py
├── requirements.txt
└── README.md                  instrucciones de la aplicación
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
  * **Módulo de Ingesta:** Lectura, validación y parseo de los archivos Excel nativos.
  * **Motor de Conciliación:** Motor de tarjetas (CLP / USD) con verificación del abono en el banco; *3-Way Match* bancario según el alcance que se confirme.
  * **Módulo de Discrepancias:** Gestión y clasificación de inconsistencias.
  * **Resultados e Historial:** Indicadores, reportes Excel e historial de conciliaciones.

####  Fase 4: Pruebas y Control de Calidad (QA)
* **Objetivo:** Asegurar la consistencia, seguridad e integridad financiera de los cálculos.
* **Actividades:**
  * Pruebas automatizadas de Django con datos sintéticos (212 pruebas: lectura de archivos, motores CLP / USD, excepciones, perfiles y pantallas).
  * Plan de pruebas funcionales: 41 casos ejecutados con evidencia.
  * Pruebas de **precisión algorítmica** utilizando volúmenes de datos reales para garantizar la exactitud en el cruce de transacciones.

####  Fase 5: Despliegue y Documentación
* **Objetivo:** Puesta en producción y entrega formal de la solución.
* **Actividades:**
  * Publicación de la aplicación en **PythonAnywhere**.
  * Elaboración del manual de usuario para el equipo operativo (Tesorería, Contabilidad, Auditoría).
  * Documentación técnica del repositorio y finalización del proyecto.

---
<a id="documentacion" name="documentacion"></a>
## 📚 Documentación del Proyecto

Las evidencias de la Fase 2 están en la carpeta [`Fase 2`](Fase%202):

| Carpeta | Contenido |
| :--- | :--- |
| `Evidencias Individuales` | Diario de reflexión de la Fase 2 de cada integrante. |
| `Evidencias Grupales` | Guía de desarrollo del proyecto (2.4) e informe final del proyecto (2.6). |
| `Evidencias Proyecto` | Presentación del proyecto (`Presentación Proyecto.pptx` y su PDF). |
| `Evidencias Proyecto/Evidencias de documentación` | Diagramas de CU (incluye nivel cero), planillas de CU, diagramas de actividad, listado de CU, RF y RNF, documentación SCRUM (análisis del caso; Product Vision; épicas, sprints e historias de usuario con criterios de aceptación y definición de terminado; priorización de HU y Product Backlog; retrospectivas de sprint) y resumen del estado de avance de los CU. |
| `Evidencias Proyecto/Evidencias de documentación/Anexos` | Carta Gantt, plan de pruebas (casos de prueba e informe), instructivo de instalación y manual de usuario. |
| `Evidencias Proyecto/Evidencias de sistema/Aplicación` | Descripción del repositorio e implementación del ambiente de desarrollo. El código está en `Conciliacion_Bancaria_2.0`. |
| `Evidencias Proyecto/Evidencias de sistema/Base de datos` | Script del sistema (poblar tablas), diccionario de datos, modelo lógico y modelo relacional. |
