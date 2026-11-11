/* Historial: selección de conciliaciones para borrar. */
(function () {
    'use strict';

    var form = document.querySelector('[data-borrar]');
    if (!form) return;
    var casillas = Array.prototype.slice.call(document.querySelectorAll('[data-seleccion]'));
    var todasPagina = document.querySelector('[data-seleccionar-pagina]');
    var boton = form.querySelector('[data-borrar-seleccionadas]');
    var contador = form.querySelector('[data-borrar-contador]');

    function actualizar() {
        var marcadas = casillas.filter(function (c) { return c.checked; }).length;
        boton.disabled = marcadas === 0;
        contador.textContent = 'Borrar seleccionadas' + (marcadas ? ' (' + marcadas + ')' : '');
        if (todasPagina) {
            todasPagina.checked = marcadas > 0 && marcadas === casillas.length;
            todasPagina.indeterminate = marcadas > 0 && marcadas < casillas.length;
        }
        casillas.forEach(function (c) {
            var fila = c.closest('tr');
            if (fila) fila.classList.toggle('fila--seleccionada', c.checked);
        });
    }

    casillas.forEach(function (c) { c.addEventListener('change', actualizar); });
    if (todasPagina) {
        todasPagina.addEventListener('change', function () {
            casillas.forEach(function (c) { c.checked = todasPagina.checked; });
            actualizar();
        });
    }
    actualizar();
})();
