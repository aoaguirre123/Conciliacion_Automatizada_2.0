/* Comportamiento común: íconos y menú lateral en pantallas chicas. */
document.addEventListener('DOMContentLoaded', function () {
    if (window.lucide) {
        window.lucide.createIcons({ attrs: { 'stroke-width': 1.75 } });
    }

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
