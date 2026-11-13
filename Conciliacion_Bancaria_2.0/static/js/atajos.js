/* Botones de ejemplo, borrar historial y restablecer la configuración: confirmación y doble clic. */
document.addEventListener('DOMContentLoaded', function () {
    // Borrar historial y restablecer configuración: pedir confirmación antes de enviar.
    document.querySelectorAll('[data-confirmar]').forEach(function (form) {
        form.addEventListener('submit', function (evento) {
            if (!window.confirm(form.getAttribute('data-confirmar'))) evento.preventDefault();
        });
    });

    // Ejemplo: avisar que se está procesando y evitar el doble clic.
    document.querySelectorAll('[data-ejemplo]').forEach(function (form) {
        var boton = form.querySelector('button');
        var texto = form.querySelector('[data-ejemplo-texto]');
        var original = texto ? texto.textContent : '';
        form.addEventListener('submit', function (evento) {
            if (window.Progreso && window.Progreso.enviar(form)) evento.preventDefault();
            if (texto) texto.textContent = 'Analizando archivos de ejemplo…';
            setTimeout(function () { boton.disabled = true; }, 0);
        });
        form.addEventListener('progreso:cancelado', function () {
            boton.disabled = false;
            if (texto) texto.textContent = original;
        });
    });
});
