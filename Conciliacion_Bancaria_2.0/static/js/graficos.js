/* Resumen gráfico: muestra el detalle de cada barra, segmento o columna al pasar el mouse o con el teclado. */
(function () {
    'use strict';

    document.querySelectorAll('.graficos').forEach(function (bloque) {
        var tip = bloque.querySelector('.grafico-tip');
        if (!tip) return;

        function mostrar(marca) {
            var partes = (marca.getAttribute('data-tip') || '').split('|');
            tip.textContent = '';
            partes.forEach(function (texto, i) {
                var linea = document.createElement(i === 0 ? 'strong' : 'span');
                linea.textContent = texto;
                tip.appendChild(linea);
            });
            tip.hidden = false;
            var caja = bloque.getBoundingClientRect();
            var r = marca.getBoundingClientRect();
            var ancho = tip.offsetWidth;
            var x = r.left - caja.left + r.width / 2 - ancho / 2;
            x = Math.max(8, Math.min(x, caja.width - ancho - 8));
            var y = r.top - caja.top - tip.offsetHeight - 8;
            if (y < 8) y = r.bottom - caja.top + 8;
            tip.style.left = x + 'px';
            tip.style.top = y + 'px';
            marca.classList.add('es-activa');
        }

        function ocultar(marca) {
            tip.hidden = true;
            if (marca) marca.classList.remove('es-activa');
        }

        bloque.querySelectorAll('[data-tip]').forEach(function (marca) {
            marca.addEventListener('mouseenter', function () { mostrar(marca); });
            marca.addEventListener('mouseleave', function () { ocultar(marca); });
            marca.addEventListener('focus', function () { mostrar(marca); });
            marca.addEventListener('blur', function () { ocultar(marca); });
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') ocultar(bloque.querySelector('.es-activa'));
        });
    });
})();
