/* Excepciones: filtro por estado dentro de una conciliación y apertura de la que viene en el enlace (#excepcion-N). */
(function () {
    'use strict';

    document.querySelectorAll('[data-excepciones]').forEach(function (bloque) {
        var botones = bloque.querySelectorAll('[data-filtro-excepcion]');
        var tarjetas = bloque.querySelectorAll('.excepcion');
        var vacio = bloque.querySelector('[data-sin-excepciones]');

        function filtrar(clave) {
            var visibles = 0;
            tarjetas.forEach(function (t) {
                var estado = t.getAttribute('data-estado');
                var ver = clave === 'todas' || (clave === 'abiertas' ? (estado === 'pendiente' || estado === 'en_revision') : estado === clave);
                t.hidden = !ver;
                if (ver) visibles += 1;
            });
            botones.forEach(function (b) {
                var activo = b.getAttribute('data-filtro-excepcion') === clave;
                b.classList.toggle('filtro--activo', activo);
                b.setAttribute('aria-pressed', activo ? 'true' : 'false');
            });
            if (vacio) vacio.hidden = visibles > 0;
            // Lo que queda oculto por el filtro no sigue seleccionado.
            tarjetas.forEach(function (t) {
                var casilla = t.querySelector('[data-seleccion-excepcion]');
                if (t.hidden && casilla && casilla.checked) casilla.checked = false;
            });
            document.dispatchEvent(new CustomEvent('excepciones:seleccion'));
        }

        botones.forEach(function (b) {
            b.addEventListener('click', function () { filtrar(b.getAttribute('data-filtro-excepcion')); });
        });

        // Si se vuelve de guardar una excepción resuelta, mostrarla aunque el filtro sea «por gestionar».
        var destino = window.location.hash && document.getElementById(window.location.hash.slice(1));
        filtrar(destino && destino.getAttribute('data-estado') === 'resuelta' ? 'todas' : 'abiertas');
    });

    // La sección parte plegada; se abre sola si el enlace apunta a ella o a una de sus excepciones
    // (por ejemplo, al volver de guardar una).
    function abrirDesdeEnlace() {
        var marcada = window.location.hash && document.getElementById(window.location.hash.slice(1));
        if (!marcada) return;
        var seccion = marcada.closest('details[data-excepciones]');
        if (seccion) seccion.open = true;
        if (marcada.classList.contains('excepcion')) {
            marcada.classList.add('excepcion--marcada');
            marcada.scrollIntoView({ block: 'center' });
        }
    }
    abrirDesdeEnlace();
    window.addEventListener('hashchange', abrirDesdeEnlace);

    // Cambio de estado de varias a la vez: barra con la cantidad seleccionada y ventana para elegir qué hacer.
    var form = document.querySelector('[data-masivo]');
    if (form) {
        var casillas = function () { return Array.prototype.slice.call(document.querySelectorAll('[data-seleccion-excepcion]')); };
        var visibles = function () { return casillas().filter(function (c) { return !c.closest('.excepcion').hidden; }); };
        var todas = form.querySelector('[data-seleccionar-excepciones]');
        var barra = form.querySelector('[data-masivo-barra]');
        var ventana = form.querySelector('[data-masivo-ventana]');

        var actualizar = function () {
            var marcadas = casillas().filter(function (c) { return c.checked; }).length;
            var vis = visibles();
            form.querySelectorAll('[data-masivo-n]').forEach(function (n) { n.textContent = marcadas; });
            form.querySelectorAll('[data-masivo-plural]').forEach(function (p) { p.textContent = marcadas === 1 ? '' : 's'; });
            form.querySelectorAll('[data-masivo-plural-es]').forEach(function (p) { p.textContent = marcadas === 1 ? 'ón' : 'ones'; });
            barra.hidden = marcadas === 0;
            casillas().forEach(function (c) { c.closest('.excepcion').classList.toggle('excepcion--seleccionada', c.checked); });
            if (todas) {
                var marcadasVisibles = vis.filter(function (c) { return c.checked; }).length;
                todas.checked = vis.length > 0 && marcadasVisibles === vis.length;
                todas.indeterminate = marcadasVisibles > 0 && marcadasVisibles < vis.length;
                todas.closest('.masivo__todas').hidden = vis.length === 0;
            }
        };

        document.addEventListener('change', function (e) {
            if (e.target.matches('[data-seleccion-excepcion]')) actualizar();
        });
        document.addEventListener('excepciones:seleccion', actualizar);
        if (todas) {
            todas.addEventListener('change', function () {
                visibles().forEach(function (c) { c.checked = todas.checked; });
                actualizar();
            });
        }
        form.querySelector('[data-masivo-limpiar]').addEventListener('click', function () {
            casillas().forEach(function (c) { c.checked = false; });
            actualizar();
        });
        form.querySelector('[data-masivo-abrir]').addEventListener('click', function () {
            if (ventana.showModal) ventana.showModal(); else ventana.setAttribute('open', '');
            var foco = ventana.querySelector('input[name="estado"]:checked') || ventana.querySelector('input');
            if (foco) foco.focus();
        });
        form.querySelector('[data-masivo-cerrar]').addEventListener('click', function () {
            if (ventana.close) ventana.close(); else ventana.removeAttribute('open');
        });
        form.addEventListener('submit', function () {
            form.querySelector('button[type="submit"]').disabled = true;
        });
        actualizar();
    }
})();
