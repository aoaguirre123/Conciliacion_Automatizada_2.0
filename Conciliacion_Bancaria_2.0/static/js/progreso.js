/* Pantalla de progreso al conciliar.

   Los formularios con data-progreso se envían en segundo plano y muestran:
   1. Subida de los archivos: avance real (bytes enviados).
   2. Análisis en el servidor: por etapas (data-progreso-pasos="Paso 1|Paso 2|..."). El servidor
      gratuito atiende de a una petición, así que no se le puede preguntar el avance mientras
      trabaja: la barra avanza según el tamaño de los archivos y el tiempo transcurrido es real.
   3. Al terminar abre el resultado. Si el servidor devuelve la página con errores, la muestra;
      si falla o no responde, lo dice y permite volver a intentar.

   Uso: window.Progreso.enviar(form). Si el navegador no lo soporta, el formulario se envía normal.
*/
(function () {
    'use strict';

    var SUBIDA = 30;      // % de la barra que corresponde a subir los archivos
    var TOPE = 96;        // la barra estimada nunca llega sola al 100 %

    function tamano(bytes) {
        if (bytes < 1024 * 1024) return Math.max(1, Math.round(bytes / 1024)) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1).replace('.', ',') + ' MB';
    }

    function reloj(segundos) {
        var m = Math.floor(segundos / 60);
        var s = Math.floor(segundos % 60);
        return m + ':' + (s < 10 ? '0' : '') + s;
    }

    function pesoFormulario(form) {
        var total = 0;
        form.querySelectorAll('input[type="file"]').forEach(function (e) {
            Array.prototype.forEach.call(e.files || [], function (a) { total += a.size; });
        });
        return total;
    }

    function crearPantalla(titulo, pasos, conSubida) {
        var capa = document.createElement('div');
        capa.className = 'progreso';
        capa.setAttribute('role', 'dialog');
        capa.setAttribute('aria-modal', 'true');
        capa.setAttribute('aria-labelledby', 'progreso-titulo');
        var lista = (conSubida ? ['Subiendo los archivos'] : []).concat(pasos).concat(['Abriendo el resultado']);
        capa.innerHTML =
            '<div class="progreso__caja">' +
            '  <div class="progreso__cabeza">' +
            '    <span class="progreso__giro" aria-hidden="true"></span>' +
            '    <div><h2 id="progreso-titulo">' + titulo + '</h2>' +
            '    <p class="progreso__estado" aria-live="polite" data-estado>Preparando…</p></div>' +
            '  </div>' +
            '  <div class="progreso__barra" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" aria-labelledby="progreso-titulo">' +
            '    <span class="progreso__relleno" data-relleno></span>' +
            '  </div>' +
            '  <div class="progreso__cifras"><span data-porcentaje>0 %</span><span>Tiempo: <strong data-tiempo>0:00</strong></span></div>' +
            '  <ol class="progreso__pasos">' + lista.map(function (p) { return '<li>' + p + '</li>'; }).join('') + '</ol>' +
            '  <p class="progreso__nota" data-nota>No cierres ni recargues esta página.</p>' +
            '  <div class="progreso__error" data-error hidden></div>' +
            '</div>';
        document.body.appendChild(capa);
        document.body.classList.add('con-progreso');
        return capa;
    }

    function enviar(form) {
        if (!window.FormData || !window.XMLHttpRequest) return false;

        var pasos = (form.getAttribute('data-progreso-pasos') || 'Analizando los archivos').split('|');
        var titulo = form.getAttribute('data-progreso-titulo') || 'Conciliando';
        var peso = pesoFormulario(form);
        var conSubida = peso > 0;
        var capa = crearPantalla(titulo, pasos, conSubida);
        var el = function (sel) { return capa.querySelector('[data-' + sel + ']'); };
        var barra = capa.querySelector('[role="progressbar"]');
        var items = capa.querySelectorAll('.progreso__pasos li');
        // Segundos que se estima que demora el análisis: más archivos, más tiempo.
        var estimado = 6 + (peso / (1024 * 1024)) * 10;
        var inicio = Date.now();
        var finSubida = null;
        var ultimoAvance = Date.now();   // último aviso de avance de la subida
        var porcentaje = 0;
        var terminado = false;

        function marcar(indice) {
            items.forEach(function (li, i) {
                li.classList.toggle('hecho', i < indice);
                li.classList.toggle('actual', i === indice);
            });
        }

        function mostrar(valor, texto) {
            porcentaje = Math.max(porcentaje, Math.min(100, valor));
            el('relleno').style.width = porcentaje + '%';
            barra.setAttribute('aria-valuenow', String(Math.round(porcentaje)));
            el('porcentaje').textContent = Math.round(porcentaje) + ' %';
            if (texto) el('estado').textContent = texto;
        }

        // Avance del análisis en el servidor, estimado según el tiempo.
        var temporizador = setInterval(function () {
            var segundos = (Date.now() - inicio) / 1000;
            el('tiempo').textContent = reloj(segundos);
            // Si el navegador no informa el avance de la subida, se pasa igual a las etapas del análisis.
            if (conSubida && finSubida === null && Date.now() - ultimoAvance > 4000) finSubida = Date.now();
            if (terminado || (conSubida && finSubida === null)) return;
            var t = (Date.now() - (finSubida || inicio)) / 1000;
            var fraccion = 1 - Math.exp(-t / estimado);   // rápido al comienzo, más lento al final
            var desde = conSubida ? SUBIDA : 0;
            mostrar(desde + (TOPE - desde) * fraccion);
            var paso = Math.min(pasos.length - 1, Math.floor(fraccion * pasos.length * 1.15));
            marcar((conSubida ? 1 : 0) + paso);
            el('estado').textContent = pasos[paso] + '…';
            if (segundos > 45) {
                el('nota').textContent = 'Sigue trabajando. En el servidor actual una conciliación grande puede tardar un par de minutos; no cierres esta página.';
            }
        }, 250);

        function fallo(mensaje) {
            terminado = true;
            clearInterval(temporizador);
            capa.classList.add('progreso--error');
            el('estado').textContent = 'No se pudo terminar';
            el('nota').hidden = true;
            var caja = el('error');
            caja.hidden = false;
            caja.innerHTML = '<p></p><button type="button" class="boton boton--principal">Volver a intentar</button>';
            caja.querySelector('p').textContent = mensaje;
            caja.querySelector('button').addEventListener('click', function () {
                capa.remove();
                document.body.classList.remove('con-progreso');
                form.dispatchEvent(new CustomEvent('progreso:cancelado'));
            });
            caja.querySelector('button').focus();
        }

        var xhr = new XMLHttpRequest();
        xhr.open('POST', form.getAttribute('action') || window.location.href);
        xhr.setRequestHeader('X-Progreso', '1');

        if (conSubida) {
            marcar(0);
            mostrar(0, 'Subiendo ' + tamano(peso) + '…');
            xhr.upload.addEventListener('progress', function (e) {
                ultimoAvance = Date.now();
                if (!e.lengthComputable) return;
                mostrar(SUBIDA * e.loaded / e.total, 'Subiendo los archivos: ' + tamano(e.loaded) + ' de ' + tamano(e.total));
            });
            xhr.upload.addEventListener('load', function () {
                finSubida = Date.now();
                mostrar(SUBIDA);
            });
        }

        xhr.addEventListener('load', function () {
            var tipo = xhr.getResponseHeader('Content-Type') || '';
            if (xhr.status === 200 && tipo.indexOf('application/json') === 0) {
                terminado = true;
                clearInterval(temporizador);
                marcar(items.length - 1);
                mostrar(100, 'Listo. Abriendo el resultado…');
                var datos = JSON.parse(xhr.responseText);
                window.location.assign(datos.url);
                return;
            }
            if (xhr.status === 200 && tipo.indexOf('text/html') === 0) {
                // La página volvió con avisos (por ejemplo, un archivo que no corresponde): se muestra tal cual.
                terminado = true;
                clearInterval(temporizador);
                // Si la sesión había terminado, la respuesta es el login: dejar su dirección en la barra.
                if (xhr.responseURL && window.history.replaceState) window.history.replaceState(null, '', xhr.responseURL);
                document.open();
                document.write(xhr.responseText);
                document.close();
                return;
            }
            if (xhr.status === 413) {
                fallo('Los archivos son demasiado grandes para el servidor. Prueba con menos archivos a la vez.');
            } else if (xhr.status === 502 || xhr.status === 503 || xhr.status === 504) {
                fallo('El servidor tardó demasiado en responder (código ' + xhr.status + '). Espera un momento y vuelve a intentar; si se repite, concilia menos días a la vez.');
            } else if (xhr.status === 403) {
                fallo('Tu sesión terminó o la página quedó abierta mucho tiempo. Recarga la página, inicia sesión y vuelve a cargar los archivos.');
            } else {
                fallo('El servidor respondió con un error (código ' + xhr.status + '). Vuelve a intentar; si se repite, avisa al administrador indicando la hora.');
            }
        });
        xhr.addEventListener('error', function () {
            fallo('Se perdió la conexión con el servidor. Revisa tu conexión a internet y vuelve a intentar.');
        });

        xhr.send(new FormData(form));
        return true;
    }

    window.Progreso = { enviar: enviar };
})();
