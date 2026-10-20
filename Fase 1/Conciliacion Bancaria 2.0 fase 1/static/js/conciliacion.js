/* Formularios de conciliación: estado de cada archivo, reglas de carga y envío.

   Las reglas salen del HTML:
   - data-obligatorio en un input: el archivo es necesario.
   - data-requiere="id" en un input: si se carga, también se necesita ese otro archivo.
   - data-alguno="id1,id2" y data-alguno-texto en el formulario: al menos uno de ellos.
*/
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-analisis]').forEach(iniciar);
});

function iniciar(form) {
    var cajas = form.querySelectorAll('[data-archivo]');
    var entradas = form.querySelectorAll('[data-archivo] input[type="file"]');
    var boton = form.querySelector('[data-analizar]');
    var textoBoton = form.querySelector('[data-analizar-texto]');
    var textoOriginal = textoBoton.textContent;
    var nota = form.querySelector('[data-nota]');
    var contador = form.querySelector('[data-contador]');
    var total = form.querySelector('[data-total]');
    if (total) total.textContent = entradas.length;

    function entrada(id) { return document.getElementById(id); }
    function cargado(id) {
        var e = entrada(id);
        return !!(e && e.files && e.files.length);
    }
    function nombre(id) {
        var e = entrada(id);
        return e ? e.getAttribute('data-nombre') : id;
    }
    function tamano(bytes) {
        if (bytes < 1024 * 1024) return Math.max(1, Math.round(bytes / 1024)) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1).replace('.', ',') + ' MB';
    }

    function problema(cantidad) {
        var obligatorios = form.querySelectorAll('input[data-obligatorio]');
        for (var i = 0; i < obligatorios.length; i++) {
            if (!cargado(obligatorios[i].id)) return 'Falta el archivo ' + obligatorios[i].getAttribute('data-nombre') + '.';
        }
        var alguno = form.getAttribute('data-alguno');
        if (alguno && !alguno.split(',').some(cargado)) return form.getAttribute('data-alguno-texto');
        if (cantidad === 0) return 'Carga al menos un archivo para comenzar.';
        for (var j = 0; j < entradas.length; j++) {
            var requiere = entradas[j].getAttribute('data-requiere');
            if (requiere && cargado(entradas[j].id) && !cargado(requiere)) {
                return 'Para ' + nombre(entradas[j].id) + ' también necesitas ' + nombre(requiere) + '.';
            }
        }
        return '';
    }

    function actualizar() {
        var cantidad = 0;
        cajas.forEach(function (caja) {
            var e = caja.querySelector('input[type="file"]');
            var detalle = caja.querySelector('[data-detalle]');
            var archivo = e.files && e.files[0];
            caja.classList.toggle('cargado', !!archivo);
            detalle.textContent = archivo ? archivo.name + ' (' + tamano(archivo.size) + ')' : detalle.getAttribute('data-vacio');
            var pastilla = form.querySelector('[data-pastilla="' + e.id + '"]');
            if (pastilla) pastilla.classList.toggle('cargado', !!archivo);
            if (archivo) cantidad += 1;
        });
        if (contador) contador.textContent = cantidad;

        var mensaje = problema(cantidad);
        boton.disabled = !!mensaje;
        nota.textContent = mensaje || 'Todo listo para analizar.';
        nota.classList.toggle('bloquea', !!mensaje && cantidad > 0);
    }

    cajas.forEach(function (caja) {
        var e = caja.querySelector('input[type="file"]');
        e.addEventListener('change', actualizar);
        e.addEventListener('dragenter', function () { caja.classList.add('arrastrando'); });
        ['dragleave', 'drop'].forEach(function (evento) {
            e.addEventListener(evento, function () { caja.classList.remove('arrastrando'); });
        });
        caja.querySelector('[data-quitar]').addEventListener('click', function () {
            e.value = '';
            actualizar();
            e.focus();
        });
    });

    form.addEventListener('submit', function (evento) {
        if (boton.disabled) { evento.preventDefault(); return; }
        boton.classList.add('ocupado');
        boton.setAttribute('aria-busy', 'true');
        textoBoton.textContent = 'Analizando…';
        var icono = boton.querySelector('svg, i');
        if (icono && window.lucide) {
            icono.outerHTML = '<i data-lucide="loader-circle" aria-hidden="true"></i>';
            window.lucide.createIcons({ attrs: { 'stroke-width': 1.75 } });
        }
        setTimeout(function () { boton.disabled = true; }, 0);
    });

    // Al volver con "atrás" el navegador puede restaurar la página: reactivar el botón.
    window.addEventListener('pageshow', function () {
        boton.classList.remove('ocupado');
        boton.removeAttribute('aria-busy');
        textoBoton.textContent = textoOriginal;
        actualizar();
    });

    actualizar();
}
