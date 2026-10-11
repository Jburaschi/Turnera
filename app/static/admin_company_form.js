/* Perfil del negocio: vista previa en vivo, contador de la descripción,
   color con su código y vista previa de logo y portada antes de guardar. */
(function () {
  const form = document.getElementById('company-form');
  if (!form) return;
  const $ = (sel) => form.querySelector(sel);

  // Contador de la descripción
  const desc = $('[data-counter]'), counter = $('[data-counter-value]');
  const updCounter = () => { if (desc && counter) counter.textContent = desc.value.length; };
  if (desc) { desc.addEventListener('input', updCounter); updCounter(); }

  // Color: muestra el código al lado
  const color = $('[data-color-input]'), hex = $('[data-color-hex]');
  if (color && hex) color.addEventListener('input', () => { hex.textContent = color.value.toUpperCase(); });

  // Vista previa: nombre, categoría y dirección
  const pv = (k) => form.querySelector(`[data-pv="${k}"]`);
  const name = $('[data-preview="name"]'), cat = $('[data-preview="category"]');
  const initials = () => (name.value.trim().slice(0, 2) || 'TU').toUpperCase();
  if (name) name.addEventListener('input', () => {
    pv('name').textContent = name.value.trim() || 'Tu negocio';
    form.querySelectorAll('[data-pv-logo-ph], [data-logo-ph]').forEach(el => { el.textContent = initials(); });
  });
  if (cat) cat.addEventListener('change', () => { pv('category').textContent = cat.value || 'Sin categoría'; });
  const street = form.querySelector('input[name="address"]'), loc = form.querySelector('input[name="locality"]');
  const updAddr = () => {
    const s = (street.value || '').trim(), l = (loc.value || '').trim();
    const line = (s ? s.charAt(0).toUpperCase() + s.slice(1) : '') + (s && l ? ' · ' + l : '');
    pv('address').textContent = line;
    form.querySelector('.cpf-preview-addr').hidden = !s;
  };
  if (street && loc) { street.addEventListener('input', updAddr); loc.addEventListener('input', updAddr); }

  // Logo y portada: vista previa del archivo elegido
  form.querySelectorAll('[data-file-preview]').forEach(input => {
    input.addEventListener('change', () => {
      const f = input.files && input.files[0];
      const nameEl = form.querySelector(`[data-file-name="${input.dataset.filePreview}"]`);
      if (!f) { if (nameEl) nameEl.textContent = ''; return; }
      if (f.size > 2 * 1024 * 1024) { alert('La imagen pesa más de 2 MB.'); input.value = ''; return; }
      const url = URL.createObjectURL(f);
      if (nameEl) nameEl.textContent = `${f.name} — se guarda al tocar “Guardar cambios”.`;
      if (input.dataset.filePreview === 'logo') {
        ['[data-logo-img]', '[data-pv-logo]'].forEach(sel => { const img = form.querySelector(sel); img.src = url; img.hidden = false; });
        form.querySelectorAll('[data-logo-ph], [data-pv-logo-ph]').forEach(el => { el.hidden = true; });
      } else {
        const frame = $('[data-cover-frame]');
        frame.style.backgroundImage = `url('${url}')`;
        const ph = $('[data-cover-ph]'); if (ph) ph.hidden = true;
      }
    });
  });
})();
