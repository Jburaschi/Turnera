/* Calendario del alta manual de turno ("Nuevo turno").
   Reemplaza el selector de fecha del navegador: pinta los días que tienen
   horarios libres para la prestación y el profesional elegidos. Al elegir un
   día actualiza #nt-date y dispara "change" (el resto del formulario carga
   los horarios igual que antes). */
(function () {
  const root = document.querySelector('[data-ntc]');
  if (!root) return;
  const input = document.getElementById('nt-date');
  const field = root.querySelector('[data-ntc-field]');
  const label = root.querySelector('[data-ntc-label]');
  const pop = root.querySelector('[data-ntc-pop]');
  const daysBox = root.querySelector('[data-ntc-days]');
  const monthEl = root.querySelector('[data-ntc-month]');
  const legend = root.querySelector('[data-ntc-legend]');
  const svcSel = document.getElementById('nt-service');
  const empSel = document.getElementById('nt-employee');
  const ignore = document.getElementById('nt-ignore-blocks');
  const MONTHS = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'];

  const pad = (n) => String(n).padStart(2, '0');
  const iso = (y, m, d) => `${y}-${pad(m)}-${pad(d)}`;
  const todayIso = (() => { const t = new Date(); return iso(t.getFullYear(), t.getMonth() + 1, t.getDate()); })();
  let [viewY, viewM] = (input.value || todayIso).split('-').map(Number);
  let counts = null;          // { 'YYYY-MM-DD': n } del mes visible, o null si falta elegir
  let loading = false;
  let reqId = 0;

  function fmt(v) { const [y, m, d] = v.split('-'); return `${d}/${m}/${y}`; }

  async function loadMonth() {
    const svc = svcSel && svcSel.value, emp = empSel && empSel.value;
    counts = null;
    if (!svc || !emp || !window.TURNEX_ADMIN_MONTH_URL) { render(); return; }
    loading = true; render();
    const my = ++reqId;
    const url = `${window.TURNEX_ADMIN_MONTH_URL}?service_id=${svc}&employee_id=${emp}&year=${viewY}&month=${viewM}&ignore_blocks=${ignore && ignore.checked ? '1' : '0'}`;
    try {
      const res = await fetch(url, { credentials: 'same-origin' });
      const data = await res.json();
      if (my !== reqId) return;           // llegó tarde: ya se pidió otro mes
      counts = data;
    } catch (e) {
      if (my === reqId) counts = null;
    } finally {
      if (my === reqId) { loading = false; render(); }
    }
  }

  function render() {
    const mName = MONTHS[viewM - 1];
    monthEl.textContent = `${mName.charAt(0).toUpperCase() + mName.slice(1)} de ${viewY}`;
    const first = new Date(viewY, viewM - 1, 1);
    const lead = (first.getDay() + 6) % 7;       // lunes = 0
    const days = new Date(viewY, viewM, 0).getDate();
    const ready = counts && !loading;
    let html = '';
    for (let i = 0; i < lead; i++) html += '<span class="ntc-day ntc-day--empty"></span>';
    for (let d = 1; d <= days; d++) {
      const v = iso(viewY, viewM, d);
      const n = ready ? (counts[v] || 0) : null;
      const cls = ['ntc-day'];
      if (n > 0) cls.push('is-free');
      else if (n === 0) cls.push('is-none');
      if (v < todayIso) cls.push('is-past');
      if (v === todayIso) cls.push('is-today');
      if (v === input.value) cls.push('is-selected');
      const title = n === null ? '' : (n > 0 ? `${n} horario${n !== 1 ? 's' : ''} libre${n !== 1 ? 's' : ''}` : 'Sin horarios libres');
      html += `<button type="button" class="${cls.join(' ')}" data-day="${v}" title="${title}" aria-label="${d} de ${MONTHS[viewM - 1]}${title ? ': ' + title : ''}">${d}</button>`;
    }
    daysBox.innerHTML = html;
    daysBox.classList.toggle('is-loading', loading);
    if (!svcSel || !svcSel.value || !empSel || !empSel.value) {
      legend.innerHTML = 'Elegí prestación y profesional para ver los días libres.';
      legend.classList.add('is-hint');
    } else {
      legend.innerHTML = loading ? 'Buscando días libres…' : '<i></i> Con turnos libres';
      legend.classList.remove('is-hint');
    }
  }

  function open() {
    const [y, m] = (input.value || todayIso).split('-').map(Number);
    if (y !== viewY || m !== viewM) { viewY = y; viewM = m; loadMonth(); } else render();
    pop.hidden = false; field.setAttribute('aria-expanded', 'true');
    requestAnimationFrame(() => pop.scrollIntoView({ block: 'nearest', behavior: 'smooth' }));
  }
  function close() { pop.hidden = true; field.setAttribute('aria-expanded', 'false'); }

  function choose(v) {
    input.value = v;
    label.textContent = fmt(v);
    input.dispatchEvent(new Event('change', { bubbles: true }));
    close();
  }

  field.addEventListener('click', () => (pop.hidden ? open() : close()));
  root.querySelector('[data-ntc-prev]').addEventListener('click', () => { if (--viewM < 1) { viewM = 12; viewY--; } loadMonth(); });
  root.querySelector('[data-ntc-next]').addEventListener('click', () => { if (++viewM > 12) { viewM = 1; viewY++; } loadMonth(); });
  root.querySelector('[data-ntc-today]').addEventListener('click', () => {
    const [y, m] = todayIso.split('-').map(Number);
    if (y !== viewY || m !== viewM) { viewY = y; viewM = m; loadMonth(); }
    choose(todayIso);
  });
  daysBox.addEventListener('click', (e) => {
    const b = e.target.closest('[data-day]');
    if (b && !b.classList.contains('is-past')) choose(b.dataset.day);
  });
  document.addEventListener('click', (e) => { if (!root.contains(e.target)) close(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });

  // Cuando cambia lo que define la disponibilidad, se recalcula el mes
  [svcSel, empSel, ignore].forEach(el => el && el.addEventListener('change', () => setTimeout(loadMonth, 0)));

  label.textContent = fmt(input.value || todayIso);
  render();
})();
