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
        }

        botones.forEach(function (b) {
            b.addEventListener('click', function () { filtrar(b.getAttribute('data-filtro-excepcion')); });
        });

        // Si se vuelve de guardar una excepción resuelta, mostrarla aunque el filtro sea «por gestionar».
        var destino = window.location.hash && document.getElementById(window.location.hash.slice(1));
        filtrar(destino && destino.getAttribute('data-estado') === 'resuelta' ? 'todas' : 'abiertas');
    });

    var marcada = window.location.hash && document.getElementById(window.location.hash.slice(1));
    if (marcada && marcada.classList.contains('excepcion')) {
        marcada.classList.add('excepcion--marcada');
        marcada.scrollIntoView({ block: 'center' });
    }
})();
