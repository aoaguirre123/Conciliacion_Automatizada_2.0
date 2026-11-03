/* Recuadro único de carga: se sueltan todos los archivos juntos y el servidor dice cuál es cuál.

   El servidor responde, por archivo, el id de la entrada oculta que le corresponde (en pesos:
   bordero, transbank, cartola; en dólares: archivo1 … archivo7). El archivo se pasa a esa
   entrada y se avisa con "change", así conciliacion.js marca las pastillas, el contador y la
   validación como si se hubiera cargado a mano. Nombre, ícono y si admite varios archivos
   salen de cada entrada oculta (data-nombre, data-icono, multiple).
*/
document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-soltar]').forEach(iniciarSoltar);
});

function iniciarSoltar(caja) {
    var form = caja.closest('form');
    var entrada = caja.querySelector('[data-soltar-entrada]');
    var lista = caja.querySelector('[data-soltados]');
    var url = caja.getAttribute('data-identificar');
    var token = form.querySelector('[name="csrfmiddlewaretoken"]');
    var soltados = [];  // { archivo, tipo, motivo, pendiente }

    var tipos = {};
    form.querySelectorAll('[data-archivo] input[type="file"]').forEach(function (e) {
        tipos[e.id] = { etiqueta: e.getAttribute('data-nombre'), icono: e.getAttribute('data-icono'), unico: !e.multiple };
    });

    function tamano(bytes) {
        if (bytes < 1024 * 1024) return Math.max(1, Math.round(bytes / 1024)) + ' KB';
        return (bytes / (1024 * 1024)).toFixed(1).replace('.', ',') + ' MB';
    }
    function mismo(a, b) {
        return a.name === b.name && a.size === b.size && a.lastModified === b.lastModified;
    }

    // Pasa los archivos reconocidos a las entradas ocultas del formulario.
    function repartir() {
        Object.keys(tipos).forEach(function (tipo) {
            var destino = document.getElementById(tipo);
            var dt = new DataTransfer();
            soltados.forEach(function (s) { if (s.tipo === tipo) dt.items.add(s.archivo); });
            destino.files = dt.files;
            destino.dispatchEvent(new Event('change'));
        });
    }

    function dibujar() {
        lista.innerHTML = '';
        soltados.forEach(function (s) {
            var tipo = tipos[s.tipo];
            var li = document.createElement('li');
            li.className = 'soltado' + (s.pendiente ? ' soltado--pendiente' : tipo ? ' soltado--reconocido' : ' soltado--error');

            var icono = document.createElement('span');
            icono.className = 'soltado__icono';
            icono.innerHTML = '<i data-lucide="' + (s.pendiente ? 'loader-circle' : tipo ? tipo.icono : 'circle-alert') + '" aria-hidden="true"></i>';

            var texto = document.createElement('span');
            texto.className = 'soltado__texto';
            var nombre = document.createElement('span');
            nombre.className = 'soltado__nombre';
            nombre.textContent = s.archivo.name;
            var detalle = document.createElement('span');
            detalle.className = 'soltado__detalle';
            detalle.textContent = s.pendiente ? 'Identificando…'
                : tipo ? tipo.etiqueta + ' · ' + tamano(s.archivo.size)
                : 'No se usará: ' + s.motivo;
            texto.appendChild(nombre);
            texto.appendChild(detalle);

            var quitar = document.createElement('button');
            quitar.type = 'button';
            quitar.className = 'soltado__quitar';
            quitar.setAttribute('aria-label', 'Quitar ' + s.archivo.name);
            quitar.innerHTML = '<i data-lucide="x" aria-hidden="true"></i>';
            quitar.addEventListener('click', function () {
                soltados.splice(soltados.indexOf(s), 1);
                dibujar();
                repartir();
            });

            li.appendChild(icono);
            li.appendChild(texto);
            li.appendChild(quitar);
            lista.appendChild(li);
        });
        if (window.lucide) window.lucide.createIcons({ attrs: { 'stroke-width': 1.75 } });
    }

    function identificar(nuevos) {
        var datos = new FormData();
        nuevos.forEach(function (s) { datos.append('archivos', s.archivo); });
        fetch(url, {
            method: 'POST',
            body: datos,
            headers: { 'X-CSRFToken': token ? token.value : '' },
            credentials: 'same-origin'
        })
            .then(function (r) {
                if (!r.ok) throw new Error('el servidor respondió ' + r.status);
                return r.json();
            })
            .then(function (respuesta) {
                nuevos.forEach(function (s, i) {
                    var dato = respuesta.archivos[i] || {};
                    s.pendiente = false;
                    s.tipo = dato.tipo || null;
                    s.motivo = dato.motivo || 'No se reconoció el archivo.';
                    // Las entradas de un solo archivo: el último que se suelta reemplaza al anterior.
                    if (s.tipo && !tipos[s.tipo]) s.tipo = null;
                    if (s.tipo && tipos[s.tipo].unico) {
                        soltados = soltados.filter(function (otro) { return otro === s || otro.tipo !== s.tipo; });
                    }
                });
            })
            .catch(function (error) {
                nuevos.forEach(function (s) {
                    s.pendiente = false;
                    s.tipo = null;
                    s.motivo = 'no se pudo identificar (' + error.message + ').';
                });
            })
            .then(function () {
                dibujar();
                repartir();
            });
    }

    function agregar(archivos) {
        var nuevos = [];
        Array.prototype.forEach.call(archivos, function (archivo) {
            if (soltados.some(function (s) { return mismo(s.archivo, archivo); })) return;
            var s = { archivo: archivo, tipo: null, motivo: '', pendiente: true };
            soltados.push(s);
            nuevos.push(s);
        });
        entrada.value = '';
        if (!nuevos.length) return;
        dibujar();
        identificar(nuevos);
    }

    entrada.addEventListener('change', function () { agregar(entrada.files); });
    entrada.addEventListener('dragenter', function () { caja.classList.add('arrastrando'); });
    ['dragleave', 'drop'].forEach(function (evento) {
        entrada.addEventListener(evento, function () { caja.classList.remove('arrastrando'); });
    });

    // No enviar mientras quedan archivos por identificar (se registra antes que conciliacion.js).
    form.addEventListener('submit', function (evento) {
        if (soltados.some(function (s) { return s.pendiente; })) {
            evento.preventDefault();
            evento.stopImmediatePropagation();
        }
    });
}
