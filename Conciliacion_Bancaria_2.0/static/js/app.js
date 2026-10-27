/* Comportamiento común: íconos y menú lateral en pantallas chicas. */
document.addEventListener('DOMContentLoaded', function () {
    function iconos() {
        if (window.lucide) {
            window.lucide.createIcons({ attrs: { 'stroke-width': 1.75 } });
        }
    }
    iconos();

    // Dólar observado: se pide aparte para que la página no espere a la API.
    document.querySelectorAll('[data-dolar]').forEach(function (caja) {
        var pedido = null;
        function cargar(fuente) {
            var url = caja.dataset.dolar + (fuente ? '&fuente=' + encodeURIComponent(fuente) : '');
            // Si se cambia de fuente mientras carga, se descarta el pedido anterior.
            if (pedido) pedido.abort();
            var este = pedido = new AbortController();
            caja.setAttribute('aria-busy', 'true');
            fetch(url, { credentials: 'same-origin', signal: este.signal })
                .then(function (r) {
                    if (!r.ok || r.redirected) throw new Error('Respuesta ' + r.status);
                    return r.text();
                })
                .then(function (html) {
                    caja.innerHTML = html;
                    iconos();
                })
                .catch(function () {
                    if (este.signal.aborted) return;
                    var aviso = caja.querySelector('[data-dolar-cargando]');
                    if (aviso) aviso.textContent = 'No se pudo obtener el valor en este momento.';
                })
                .finally(function () {
                    if (pedido === este) caja.removeAttribute('aria-busy');
                });
        }
        caja.addEventListener('click', function (e) {
            var boton = e.target.closest('[data-fuente]');
            if (boton) cargar(boton.dataset.fuente);
        });
        cargar();
    });

    var raiz = document.documentElement;
    var boton = document.querySelector('[data-menu-abrir]');
    var velo = document.querySelector('[data-menu-velo]');
    if (!boton) return;

    function abrir(abierto) {
        raiz.classList.toggle('menu-abierto', abierto);
        if (velo) velo.hidden = !abierto;
        boton.setAttribute('aria-expanded', String(abierto));
        boton.setAttribute('aria-label', abierto ? 'Cerrar menú' : 'Abrir menú');
    }

    boton.addEventListener('click', function () { abrir(!raiz.classList.contains('menu-abierto')); });
    if (velo) velo.addEventListener('click', function () { abrir(false); });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && raiz.classList.contains('menu-abierto')) {
            abrir(false);
            boton.focus();
        }
    });
});
