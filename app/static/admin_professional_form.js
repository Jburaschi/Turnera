/* Vista "Nuevo / Editar profesional": franjas horarias, prestaciones por franja,
   foto con vista previa, contador de la descripción y estado. */
(function () {
  const form = document.getElementById('pro-form');
  if (!form) return;
  const slotsBox = form.querySelector('[data-slots]');

  // ── Prestaciones del profesional (tarjetas) ───────────────────────────────
  function proServiceIds() {
    return Array.from(form.querySelectorAll('[data-pro-service]:checked')).map(cb => cb.value);
  }
  form.querySelectorAll('[data-pro-service]').forEach(cb => {
    cb.addEventListener('change', () => {
      cb.closest('.pf-service').classList.toggle('is-checked', cb.checked);
      refreshAllSlots();
    });
  });

  // ── Franjas ───────────────────────────────────────────────────────────────
  function slots() { return Array.from(slotsBox.querySelectorAll('[data-slot]')); }

  function renumber() {
    slots().forEach((row, i) => {
      row.querySelector('[data-field="weekday"]').name = `block_${i}_weekday`;
      row.querySelector('[data-field="start"]').name = `block_${i}_start`;
      row.querySelector('[data-field="end"]').name = `block_${i}_end`;
      row.querySelectorAll('.pf-slot-opt input').forEach(cb => { cb.name = `block_${i}_service_ids`; });
    });
    const one = slots().length <= 1;
    slots().forEach(r => { r.querySelector('[data-slot-remove]').disabled = one; });
  }

  // Muestra en la franja solo las prestaciones que el profesional hace.
  // Si todas están tildadas, el resumen dice "Todas"; si no, hasta 2 nombres y "+N".
  function refreshSlot(row) {
    const allowed = proServiceIds();
    const opts = Array.from(row.querySelectorAll('.pf-slot-opt'));
    let visible = 0;
    opts.forEach(opt => {
      const show = allowed.length === 0 || allowed.includes(opt.dataset.serviceOpt);
      opt.hidden = !show;
      if (show) visible++;
    });
    const shown = opts.filter(o => !o.hidden).map(o => o.querySelector('input'));
    const checked = shown.filter(cb => cb.checked);
    const summary = row.querySelector('[data-slot-summary]');
    summary.innerHTML = '';
    if (allowed.length === 0) {
      summary.innerHTML = '<span class="pf-chip pf-chip--muted">Elegí prestaciones arriba</span>';
    } else if (checked.length === 0 || checked.length === shown.length) {
      summary.innerHTML = '<span class="pf-chip pf-chip--all">Todas sus prestaciones</span>';
    } else {
      checked.slice(0, 2).forEach(cb => {
        const chip = document.createElement('span');
        chip.className = 'pf-chip';
        chip.textContent = cb.dataset.name;
        summary.appendChild(chip);
      });
      if (checked.length > 2) {
        const more = document.createElement('span');
        more.className = 'pf-chip pf-chip--more';
        more.textContent = `+${checked.length - 2}`;
        summary.appendChild(more);
      }
    }
  }
  function refreshAllSlots() { slots().forEach(refreshSlot); }

  // Al enviar, en cada franja solo viajan las prestaciones visibles; si están
  // todas tildadas se envían todas (= sin límite).
  form.addEventListener('submit', (e) => {
    const allowed = proServiceIds();
    let bad = null;
    slots().forEach(row => {
      const st = row.querySelector('[data-field="start"]').value;
      const en = row.querySelector('[data-field="end"]').value;
      if (st && en && st >= en) bad = row;
      row.querySelectorAll('.pf-slot-opt').forEach(opt => {
        const cb = opt.querySelector('input');
        cb.disabled = allowed.length > 0 && !allowed.includes(opt.dataset.serviceOpt);
      });
    });
    if (bad) {
      e.preventDefault();
      form.querySelectorAll('[data-slot-pop]').forEach(p => { p.hidden = true; });
      bad.classList.add('is-invalid');
      bad.scrollIntoView({ behavior: 'smooth', block: 'center' });
      alert('En una franja la hora "Hasta" tiene que ser posterior a "Desde".');
      form.querySelectorAll('.pf-slot-opt input').forEach(cb => { cb.disabled = false; });
    }
  });

  function closePops(except) {
    form.querySelectorAll('[data-slot-pop]').forEach(p => {
      if (p !== except) {
        p.hidden = true;
        const btn = p.closest('[data-slot-services]').querySelector('[data-slot-toggle]');
        btn.setAttribute('aria-expanded', 'false');
      }
    });
  }

  document.addEventListener('click', (e) => {
    const t = e.target;
    if (t.closest('[data-slot-add]')) {
      const base = slots()[slots().length - 1];
      const row = base.cloneNode(true);
      row.classList.remove('is-invalid');
      row.querySelector('[data-slot-pop]').hidden = true;
      slotsBox.appendChild(row);
      renumber(); refreshSlot(row);
      row.querySelector('[data-field="weekday"]').focus();
      return;
    }
    const rm = t.closest('[data-slot-remove]');
    if (rm) {
      if (slots().length > 1) { rm.closest('[data-slot]').remove(); renumber(); }
      return;
    }
    if (t.closest('[data-slot-replicate]')) {
      const mon = slots().filter(r => r.querySelector('[data-field="weekday"]').value === '0');
      if (!mon.length) { alert('Necesitás al menos una franja el lunes para replicarla.'); return; }
      ['1', '2', '3', '4'].forEach(wd => {
        // reemplaza lo que ya hubiera esos días por las franjas del lunes
        slots().filter(r => r.querySelector('[data-field="weekday"]').value === wd).forEach(r => r.remove());
        mon.forEach(m => {
          const row = m.cloneNode(true);
          row.querySelector('[data-field="weekday"]').value = wd;
          row.querySelector('[data-slot-pop]').hidden = true;
          // cloneNode no copia el estado actual de los checkbox: lo pasamos a mano
          const src = m.querySelectorAll('.pf-slot-opt input');
          row.querySelectorAll('.pf-slot-opt input').forEach((cb, k) => { cb.checked = src[k].checked; });
          slotsBox.appendChild(row);
        });
      });
      // ordenar por día y hora
      slots().sort((a, b) => {
        const da = +a.querySelector('[data-field="weekday"]').value, db = +b.querySelector('[data-field="weekday"]').value;
        return da - db || a.querySelector('[data-field="start"]').value.localeCompare(b.querySelector('[data-field="start"]').value);
      }).forEach(r => slotsBox.appendChild(r));
      renumber(); refreshAllSlots();
      return;
    }
    const tog = t.closest('[data-slot-toggle]');
    if (tog) {
      const pop = tog.closest('[data-slot-services]').querySelector('[data-slot-pop]');
      const open = pop.hidden;
      closePops(pop);
      pop.hidden = !open;
      tog.setAttribute('aria-expanded', open ? 'true' : 'false');
      return;
    }
    if (t.closest('[data-slot-close]')) { closePops(null); return; }
    const all = t.closest('[data-slot-all]');
    if (all) {
      all.closest('[data-slot]').querySelectorAll('.pf-slot-opt:not([hidden]) input').forEach(cb => { cb.checked = true; });
      refreshSlot(all.closest('[data-slot]'));
      return;
    }
    if (!t.closest('[data-slot-pop]')) closePops(null);
  });

  form.addEventListener('change', (e) => {
    const cb = e.target.closest('.pf-slot-opt input');
    if (cb) {
      const row = cb.closest('[data-slot]');
      const visibles = Array.from(row.querySelectorAll('.pf-slot-opt:not([hidden]) input'));
      if (!visibles.some(x => x.checked)) {
        cb.checked = true;
        alert('Tiene que quedar al menos una prestación tildada en la franja.');
      }
      refreshSlot(row);
    }
    if (e.target.closest('[data-field]')) e.target.closest('[data-slot]').classList.remove('is-invalid');
  });

  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closePops(null); });

  // ── Foto con vista previa ─────────────────────────────────────────────────
  const photoInput = form.querySelector('[data-photo-input]');
  if (photoInput) {
    photoInput.addEventListener('change', () => {
      const f = photoInput.files && photoInput.files[0];
      if (!f) return;
      if (f.size > 2 * 1024 * 1024) { alert('La foto pesa más de 2 MB.'); photoInput.value = ''; return; }
      const img = form.querySelector('[data-photo-preview]');
      img.src = URL.createObjectURL(f); img.hidden = false;
      form.querySelector('[data-photo-icon]').hidden = true;
      form.querySelector('[data-photo-text]').textContent = f.name;
    });
  }

  // ── Contador de la descripción y punto de estado ─────────────────────────
  const bio = form.querySelector('[data-counter]');
  const counter = form.querySelector('[data-counter-value]');
  const updCounter = () => { if (bio && counter) counter.textContent = bio.value.length; };
  if (bio) { bio.addEventListener('input', updCounter); updCounter(); }
  const st = form.querySelector('[data-status-select]');
  const dot = form.querySelector('[data-status-dot]');
  const updDot = () => { if (dot && st) dot.classList.toggle('is-off', st.value !== '1'); };
  if (st) { st.addEventListener('change', updDot); updDot(); }

  renumber(); refreshAllSlots();
})();
