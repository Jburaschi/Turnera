const root = document.getElementById('booking-root');

if (root) {
  const slug = root.dataset.slug;
  let allowAvailability = root.dataset.allowAvailability === '1';
  let allowEmployee = root.dataset.allowEmployee === '1';
  if (!allowAvailability && !allowEmployee) {
    allowAvailability = true;
    allowEmployee = true;
  }

  const serviceInput = document.getElementById('service_id');
  const employeeInput = document.getElementById('employee_id');
  const startInput = document.getElementById('start_dt');

  const bookingFlowLayout = document.getElementById('booking-flow-layout');
  const confirmScreen = document.getElementById('confirm-screen');
  const backToFlowBtn = document.getElementById('back-to-flow-btn');
  const backToFlowBtnBottom = document.getElementById('back-to-flow-btn-bottom');

  const panels = {
    service:  document.getElementById('step-service'),
    mode:     document.getElementById('step-mode'),
    employee: document.getElementById('step-employee'),
    date:     document.getElementById('step-date'),
    time:     document.getElementById('step-time'),
  };

  const servicesGrid    = document.getElementById('services-grid');
  const modeOptions     = document.getElementById('mode-options');
  const employeeOptions = document.getElementById('employee-options');
  const calendarTitle   = document.getElementById('calendar-title');
  const calendarGrid    = document.getElementById('calendar-grid');
  const timeSlots       = document.getElementById('time-slots');
  const timeContext     = document.getElementById('time-context');

  const summaryService  = document.getElementById('summary-service');
  const summaryDate     = document.getElementById('summary-date');
  const summaryTime     = document.getElementById('summary-time');
  const summaryEmployee = document.getElementById('summary-employee');
  const summaryNote     = document.getElementById('summary-note');

  const serviceStatus  = document.getElementById('service-status');
  const modeStatus     = document.getElementById('mode-status');
  const employeeStatus = document.getElementById('employee-status');
  const dateStatus     = document.getElementById('date-status');
  const timeStatus     = document.getElementById('time-status');

  const employeeStepTitle = document.getElementById('employee-step-title');
  const employeeStepHelp  = document.getElementById('employee-step-help');
  const dateStepTitle     = document.getElementById('date-step-title');
  const dateStepHelp      = document.getElementById('date-step-help');
  const timeStepTitle     = document.getElementById('time-step-title');

  const serviceModalEl = document.getElementById('serviceModal');
  const serviceModal   = serviceModalEl ? new bootstrap.Modal(serviceModalEl) : null;

  const brand = root.dataset.brand || '#3654f0';
  const summarySide = document.querySelector('.booking-confirm-summary-side');
  if (summarySide) {
    summarySide.style.background = `linear-gradient(145deg, ${brand}, #111827)`;
  }

  const urlParams = new URLSearchParams(window.location.search);
  const preselectedServiceId = Number(urlParams.get('service_id')) || null;
  let preselectedEmployeeId = Number(urlParams.get('employee_id')) || null;
  let preselectedMode = urlParams.get('mode') || null;

  let services = [];
  let employees = [];
  let currentDaySlots = [];
  let selectedService = null;
  let pendingService = null;
  let selectedMode = null;
  let selectedEmployeeId = null;
  let selectedEmployeeName = null;
  let selectedDate = null;
  let selectedTimeLabel = null;
  let selectedSlot = null;
  let currentMonth = new Date();
  currentMonth.setDate(1);

  // Stepper state: track which steps are "done" (nombres internos de los paneles)
  const stepOrder = ['service','mode','employee','date','time'];

  // El stepper visual tiene 5 pasos (sin "Modalidad" contado aparte): Servicio, Profesional, Fecha, Horario, Confirmación.
  // "mode" y "employee" iluminan el mismo círculo ("Profesional").
  const visualSteps = ['service','employee','date','time','confirm'];
  const toVisualStep = { service:'service', mode:'employee', employee:'employee', date:'date', time:'time', confirm:'confirm' };

  const flowTitleEl = document.getElementById('booking-flow-title');
  const flowSubtitleEl = document.getElementById('booking-flow-subtitle');
  const stepTitles = {
    service: ['¿Qué servicio querés reservar?', 'Elegí el servicio que mejor se adapte a vos.'],
    mode:    ['¿Cómo querés buscar tu turno?', 'Elegí la modalidad de búsqueda que preferís.'],
    employee:['¿Quién te va a atender?', 'Elegí el profesional con el que querés atenderte.'],
    date:    ['Elegí una fecha', 'Seleccioná el día que te quede mejor.'],
    time:    ['Elegí un horario', 'Seleccioná la hora dentro de los turnos disponibles.'],
    confirm: ['Confirmá tu reserva', 'Completá tus datos para finalizar la reserva.'],
  };

  function updateStepper(activeStep, completedSteps = []) {
    const visActive = toVisualStep[activeStep] || activeStep;
    const visCompleted = new Set(completedSteps.map(s => toVisualStep[s] || s));
    if (visActive === 'employee') visCompleted.delete('employee'); // no marcar "hecho" mientras seguimos eligiendo

    visualSteps.forEach(name => {
      const el = document.getElementById(`bstep-${name}`);
      if (!el) return;
      el.classList.remove('bstep--active','bstep--done','bstep--pending');
      if (visCompleted.has(name)) {
        el.classList.add('bstep--done');
      } else if (name === visActive) {
        el.classList.add('bstep--active');
      } else {
        el.classList.add('bstep--pending');
      }
    });

    const titles = stepTitles[activeStep];
    if (titles && flowTitleEl && flowSubtitleEl) {
      flowTitleEl.textContent = titles[0];
      flowSubtitleEl.textContent = titles[1];
    }
  }

  function showPanel(name) {
    Object.keys(panels).forEach(k => {
      panels[k].classList.add('d-none');
      panels[k].classList.remove('is-active');
    });
    panels[name].classList.remove('d-none');
    panels[name].classList.add('is-active');
    panels[name].scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function money(v) {
    return new Intl.NumberFormat('es-AR', { maximumFractionDigits: 0 }).format(v || 0);
  }

  function formatHumanDate(iso) {
    const [y, m, d] = iso.split('-');
    return `${d}/${m}/${y}`;
  }

  function monthName(d) {
    return d.toLocaleDateString('es-AR', { month: 'long', year: 'numeric' });
  }

  function weekdayLong(iso) {
    if (!iso) return '—';
    const [y, m, d] = iso.split('-').map(Number);
    const dt = new Date(y, m - 1, d);
    return dt.toLocaleDateString('es-AR', { weekday: 'long' });
  }

  function renderSummary(note = 'Completá tus datos para confirmar el turno.') {
    summaryService.textContent  = selectedService?.name || '-';
    summaryDate.textContent     = selectedDate ? formatHumanDate(selectedDate) : '-';
    summaryTime.textContent     = selectedTimeLabel || '-';
    summaryEmployee.textContent = selectedEmployeeName || '-';
    summaryNote.textContent     = note;
    const wk = document.getElementById('summary-weekday-label');
    const db = document.getElementById('summary-date-big');
    const tb = document.getElementById('summary-time-big');
    if (wk) wk.textContent = selectedDate ? weekdayLong(selectedDate) : '—';
    if (db) db.textContent = selectedDate ? formatHumanDate(selectedDate) : '—';
    if (tb) tb.textContent = selectedTimeLabel || '—';

    // Panel "Tu selección" (visible durante todo el flujo, no solo al confirmar)
    const liveService  = document.getElementById('live-summary-service');
    const liveEmployee = document.getElementById('live-summary-employee');
    const liveDate      = document.getElementById('live-summary-date');
    const liveTime      = document.getElementById('live-summary-time');
    const livePriceRow  = document.getElementById('live-summary-price-row');
    const livePrice      = document.getElementById('live-summary-price');
    if (liveService)  liveService.textContent  = selectedService?.name || '—';
    if (liveEmployee) liveEmployee.textContent = selectedEmployeeName || (selectedMode === 'availability' ? 'Primer disponible' : '—');
    if (liveDate)      liveDate.textContent      = selectedDate ? formatHumanDate(selectedDate) : '—';
    if (liveTime)      liveTime.textContent      = selectedTimeLabel || '—';
    if (livePrice && livePriceRow) {
      if (selectedService && selectedService.price) {
        livePrice.textContent = '$' + Number(selectedService.price).toLocaleString('es-AR');
        livePriceRow.classList.remove('d-none');
      } else {
        livePriceRow.classList.add('d-none');
      }
    }
    const confirmPrice = document.getElementById('confirm-price');
    const confirmPriceRow = document.getElementById('confirm-price-row');
    if (confirmPrice && confirmPriceRow) {
      if (selectedService && selectedService.price) {
        confirmPrice.textContent = '$' + Number(selectedService.price).toLocaleString('es-AR');
        confirmPriceRow.style.display = 'flex';
      } else {
        confirmPriceRow.style.display = 'none';
      }
    }
    const liveEditService = document.getElementById('live-edit-service');
    if (liveEditService) liveEditService.classList.toggle('d-none', !selectedService);
    document.querySelectorAll('.booking-side-row').forEach(row => row.classList.remove('is-filled'));
    if (selectedService)  document.getElementById('live-row-service')?.classList.add('is-filled');
    if (selectedEmployeeName || selectedMode === 'availability') document.getElementById('live-row-employee')?.classList.add('is-filled');
    if (selectedDate)      document.getElementById('live-row-date')?.classList.add('is-filled');
    if (selectedTimeLabel) document.getElementById('live-row-time')?.classList.add('is-filled');
  }

  function resetSummary() {
    renderSummary('Completá tus datos para confirmar el turno.');
  }

  let holdCountdownTimer = null;

  async function startSlotHold() {
    const holdBox = document.getElementById('slot-hold-box');
    const holdBoxText = document.getElementById('slot-hold-text');
    if (holdCountdownTimer) { clearInterval(holdCountdownTimer); holdCountdownTimer = null; }
    if (!selectedService || !selectedEmployeeId || !startInput.value) return;

    try {
      const res = await fetch(`/${slug}/hold-slot`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({
          service_id: selectedService.id,
          employee_id: selectedEmployeeId,
          start_dt: startInput.value,
        }),
      });
      const data = await res.json();
      if (!res.ok || !data.ok) {
        if (holdBox) holdBox.classList.add('d-none');
        const warn = document.getElementById('slot-taken-warning');
        if (warn) warn.classList.remove('d-none');
        return;
      }
      const expiresAt = new Date(data.expires_at);
      if (holdBox) holdBox.classList.remove('d-none');
      const warn = document.getElementById('slot-taken-warning');
      if (warn) warn.classList.add('d-none');

      const tick = () => {
        const msLeft = expiresAt - new Date();
        if (msLeft <= 0) {
          clearInterval(holdCountdownTimer);
          if (holdBoxText) holdBoxText.textContent = 'El tiempo de reserva expiró. Podés intentar confirmar igual.';
          return;
        }
        const totalSec = Math.floor(msLeft / 1000);
        const mm = String(Math.floor(totalSec / 60)).padStart(2, '0');
        const ss = String(totalSec % 60).padStart(2, '0');
        if (holdBoxText) holdBoxText.textContent = `Tenés ${mm}:${ss} para confirmar tu reserva.`;
      };
      tick();
      holdCountdownTimer = setInterval(tick, 1000);
    } catch (e) {
      // Si falla la red, no bloqueamos el flujo: el chequeo real vuelve a pasar al confirmar.
    }
  }

  function releaseSlotHold() {
    if (holdCountdownTimer) { clearInterval(holdCountdownTimer); holdCountdownTimer = null; }
    if (navigator.sendBeacon) {
      const data = new Blob([], { type: 'application/x-www-form-urlencoded' });
      navigator.sendBeacon(`/${slug}/release-hold`, data);
    }
  }

  function showConfirmScreen() {
    bookingFlowLayout.classList.add('d-none');
    confirmScreen.classList.remove('d-none');
    window.scrollTo({ top: 0, behavior: 'smooth' });
    updateStepper('confirm', stepOrder);
    startSlotHold();
  }

  function hideConfirmScreen() {
    confirmScreen.classList.add('d-none');
    bookingFlowLayout.classList.remove('d-none');
    releaseSlotHold();
  }

  function showFlow() {
    hideConfirmScreen();
    if (selectedMode === 'availability') {
      showPanel('employee');
      updateStepper('employee', ['service','mode','date','time']);
    } else {
      showPanel('time');
      updateStepper('time', ['service','mode','employee','date']);
    }
  }

  function resetAfterService() {
    selectedMode = null;
    selectedEmployeeId = null;
    selectedEmployeeName = null;
    selectedDate = null;
    selectedTimeLabel = null;
    selectedSlot = null;
    currentDaySlots = [];
    employees = [];

    employeeInput.value = '';
    startInput.value = '';

    modeStatus.textContent     = 'Elegí una modalidad';
    employeeStatus.textContent = 'Elegí un profesional';
    dateStatus.textContent     = 'Elegí una fecha';
    timeStatus.textContent     = 'Elegí un horario';

    resetSummary();
    hideConfirmScreen();

    timeContext.textContent = 'Primero elegí una fecha.';
    employeeOptions.innerHTML = '';
    calendarGrid.innerHTML = '';
    timeSlots.innerHTML = '';

    ['mode','employee','date','time'].forEach(k => panels[k].classList.add('d-none'));
  }

  function markSelectedServiceCard(serviceId) {
    document.querySelectorAll('.service-card').forEach(card => {
      card.classList.toggle('active', Number(card.dataset.serviceId) === serviceId);
    });
  }

  function applySelectedService(service, { fromPreselected = false } = {}) {
    pendingService = null;
    selectedService = service;
    serviceInput.value = selectedService.id;

    markSelectedServiceCard(selectedService.id);
    resetAfterService();

    serviceStatus.textContent = selectedService.name;
    showPanel('mode');
    renderModes();
    renderSummary('Ahora elegí cómo querés buscar el turno.');
    updateStepper('mode', ['service']);

    if (preselectedEmployeeId && allowEmployee) {
      document.querySelector('.mode-option[data-mode="employee"]')?.click();
    } else if (preselectedMode) {
      const modeToClick = preselectedMode;
      preselectedMode = null;
      document.querySelector(`.mode-option[data-mode="${modeToClick}"]`)?.click();
    }
  }

  function renderServices(filterText = '') {
    const q = filterText.trim().toLowerCase();
    const filtered = q
      ? services.filter(s => (s.name + ' ' + (s.short_description || '') + ' ' + (s.long_description || '')).toLowerCase().includes(q))
      : services;

    if (!filtered.length) {
      servicesGrid.innerHTML = `<div class="booking-empty-hint">No encontramos servicios que coincidan con "${filterText}".</div>`;
      return;
    }

    servicesGrid.innerHTML = filtered.map(service => `
      <div class="service-row ${pendingService?.id === service.id ? 'active' : ''}" data-service-id="${service.id}">
        <span class="service-row-icon" style="background:${service.color}22;color:${service.color}">${SERVICE_ICON_SVG}</span>
        <div class="service-row-body">
          <div class="service-row-top">
            <strong>${service.name}</strong>
            <span class="service-row-duration">${ic('clock')} ${service.duration_min} min</span>
          </div>
          ${service.short_description ? `<div class="service-row-sub">${service.short_description}</div>` : ''}
          ${service.long_description ? `<div class="service-row-desc">${service.long_description}</div>` : ''}
        </div>
        <div class="service-row-right">
          <div class="service-row-price">$${money(service.price)}</div>
          <span class="service-row-check">${pendingService?.id === service.id ? ic('check') : ic('chevron-right')}</span>
        </div>
      </div>
    `).join('');

    document.querySelectorAll('.service-row').forEach(row => {
      row.addEventListener('click', () => {
        const clicked = services.find(s => s.id === Number(row.dataset.serviceId));
        if (!clicked) return;
        pendingService = clicked;
        renderServices(document.getElementById('service-search')?.value || '');
        const continueBtn = document.getElementById('continue-service-btn');
        if (continueBtn) continueBtn.disabled = false;
      });
    });
  }

  const SERVICE_ICON_SVG = '<svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="7" width="19" height="13" rx="2"/><path d="M8 7V5a2 2 0 012-2h4a2 2 0 012 2v2"/><path d="M2.5 13h19"/></svg>';
  function ic(name) {
    if (name === 'clock') return '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>';
    if (name === 'check') return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 13l4 4L19 7"/></svg>';
    return '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>';
  }

  document.getElementById('service-search')?.addEventListener('input', (e) => renderServices(e.target.value));

  document.getElementById('continue-service-btn')?.addEventListener('click', () => {
    if (!pendingService) return;
    applySelectedService(pendingService);
  });

  function renderModes() {
    const cards = [];
    if (allowAvailability) {
      cards.push(`
        <div class="mode-option" data-mode="availability">
          <div class="mode-icon">📅</div>
          <h6>Primer turno disponible</h6>
          <div class="small opacity-75">Elegís la fecha y hora; te mostramos los profesionales disponibles.</div>
        </div>`);
    }
    if (allowEmployee) {
      cards.push(`
        <div class="mode-option" data-mode="employee">
          <div class="mode-icon">👤</div>
          <h6>Elegir profesional</h6>
          <div class="small opacity-75">Primero elegís quién te atiende y después ves sus fechas disponibles.</div>
        </div>`);
    }
    if (!cards.length) {
      modeOptions.innerHTML = '<p class="text-secondary small mb-0">Activá al menos una forma de búsqueda en Reglas de reserva.</p>';
      return;
    }
    modeOptions.innerHTML = cards.join('');

    document.querySelectorAll('.mode-option').forEach(option => {
      option.addEventListener('click', async () => {
        document.querySelectorAll('.mode-option').forEach(x => x.classList.remove('active'));
        option.classList.add('active');
        selectedMode = option.dataset.mode;
        modeStatus.textContent = selectedMode === 'availability' ? 'Primer turno disponible' : 'Elegir profesional';

        selectedEmployeeId = null;
        selectedEmployeeName = null;
        selectedDate = null;
        selectedTimeLabel = null;
        selectedSlot = null;
        employeeInput.value = '';
        startInput.value = '';
        timeSlots.innerHTML = '';
        employeeOptions.innerHTML = '';
        resetSummary();
        hideConfirmScreen();

        if (selectedMode === 'availability') {
          employeeStepTitle.textContent = 'Profesional disponible';
          employeeStepHelp.textContent  = 'Elegí entre los profesionales disponibles para ese horario.';
          dateStepTitle.textContent     = 'Elegí una fecha';
          dateStepHelp.textContent      = 'Elegí primero la fecha disponible.';
          if (timeStepTitle) timeStepTitle.textContent = 'Elegí un horario';

          ['employee','time'].forEach(k => panels[k].classList.add('d-none'));

          showPanel('date');
          renderMonth();
          updateStepper('date', ['service','mode']);
        } else {
          employeeStepTitle.textContent = 'Elegí un profesional';
          employeeStepHelp.textContent  = 'Seleccioná con quién querés atenderte.';
          dateStepTitle.textContent     = 'Elegí una fecha';
          dateStepHelp.textContent      = 'Elegí una fecha dentro de la agenda del profesional.';

          ['date','time'].forEach(k => panels[k].classList.add('d-none'));

          await loadEmployees();
          showPanel('employee');
          updateStepper('employee', ['service','mode']);
        }
      });
    });
  }

  async function loadEmployees() {
    employees = await fetch(`/api/${slug}/employees?service_id=${selectedService.id}`).then(r => r.json());
    renderEmployeeCards(employees, chooseEmployeeForMode);
  }

  function renderEmployeeCards(items, clickHandler) {
    employeeOptions.innerHTML = items.map(e => {
      const id   = e.id ?? e.employee_id;
      const name = e.name ?? e.employee_name ?? 'Profesional';
      const color = e.color ?? '';
      return `
        <button type="button" class="employee-card w-100" data-id="${id}" data-name="${name}">
          ${color ? `<div class="emp-dot" style="background:${color}"></div>` : '<div class="emp-dot"></div>'}
          <div class="fw-semibold">${name}</div>
          <div class="small text-secondary mt-1">Profesional</div>
        </button>`;
    }).join('');
    document.querySelectorAll('.employee-card').forEach(card => {
      card.addEventListener('click', () => clickHandler(card));
    });

    if (preselectedEmployeeId) {
      const match = document.querySelector(`.employee-card[data-id="${preselectedEmployeeId}"]`);
      preselectedEmployeeId = null; // solo se auto-aplica una vez
      if (match) match.click();
    }
  }

  function chooseEmployeeForMode(card) {
    document.querySelectorAll('.employee-card').forEach(x => x.classList.remove('active'));
    card.classList.add('active');
    selectedEmployeeId   = Number(card.dataset.id);
    selectedEmployeeName = card.dataset.name;
    employeeInput.value  = selectedEmployeeId;
    employeeStatus.textContent = selectedEmployeeName;

    if (selectedMode === 'employee') {
      renderSummary('Ahora elegí la fecha y la hora para continuar.');
      panels['time'].classList.add('d-none');
      showPanel('date');
      renderMonth();
      updateStepper('date', ['service','mode','employee']);
    } else {
      attachEmployeeToSelectedTime(selectedEmployeeId);
    }
  }

  async function renderMonth() {
    if (!selectedService) return;
    const year = currentMonth.getFullYear();
    const month = currentMonth.getMonth() + 1;
    const qs = new URLSearchParams({ service_id: selectedService.id, year, month });
    if (selectedMode === 'employee' && selectedEmployeeId) qs.set('employee_id', selectedEmployeeId);

    const summary = await fetch(`/api/${slug}/availability/month?${qs.toString()}`).then(r => r.json());
    calendarTitle.textContent = monthName(currentMonth);

    const start  = new Date(year, month - 1, 1);
    const end    = new Date(year, month, 0);
    calendarGrid.innerHTML = '';

    ['Lu','Ma','Mi','Ju','Vi','Sa','Do'].forEach(label => {
      const head = document.createElement('div');
      head.className = 'fw-semibold text-secondary small p-2 text-center';
      head.textContent = label;
      calendarGrid.appendChild(head);
    });

    const offset = (start.getDay() + 6) % 7;
    for (let i = 0; i < offset; i++) calendarGrid.appendChild(document.createElement('div'));

    for (let day = 1; day <= end.getDate(); day++) {
      const cellDate = new Date(year, month - 1, day);
      const iso = cellDate.toISOString().slice(0, 10);
      const count = summary[iso] || 0;
      const classes = ['calendar-cell', count > 0 ? 'available' : 'unavailable'];
      if (iso === selectedDate) classes.push('selected');

      const cell = document.createElement('button');
      cell.type = 'button';
      cell.className = classes.join(' ');
      cell.innerHTML = `<span>${day}</span><small>${count > 0 ? count : ''}</small>`;
      if (count > 0) cell.addEventListener('click', () => selectDate(iso));
      else cell.disabled = true;
      calendarGrid.appendChild(cell);
    }
  }

  async function selectDate(iso) {
    selectedDate = iso;
    selectedSlot = null;
    selectedTimeLabel = null;

    if (selectedMode === 'availability') {
      selectedEmployeeId = null;
      selectedEmployeeName = null;
      employeeInput.value = '';
      employeeStatus.textContent = 'Elegí un profesional';
      panels['employee'].classList.add('d-none');
    }

    startInput.value = '';
    dateStatus.textContent = formatHumanDate(iso);
    timeStatus.textContent = 'Elegí un horario';
    renderSummary('Ahora elegí una hora para continuar.');
    timeContext.textContent = `${selectedService.name} · ${formatHumanDate(iso)}. Ahora elegí una hora.`;

    const qs = new URLSearchParams({ service_id: selectedService.id, date: iso });
    if (selectedMode === 'employee' && selectedEmployeeId) qs.set('employee_id', selectedEmployeeId);

    currentDaySlots = await fetch(`/api/${slug}/availability/day?${qs.toString()}`).then(r => r.json());

    renderTimeOptions();
    panels['time'].classList.remove('d-none');
    showPanel('time');
    hideConfirmScreen();
    renderMonth();

    const completed = selectedMode === 'availability'
      ? ['service','mode','date']
      : ['service','mode','employee','date'];
    updateStepper('time', completed);
  }

  function renderTimeOptions() {
    timeSlots.innerHTML = '';
    if (!currentDaySlots.length) {
      timeSlots.innerHTML = '<div class="text-secondary small">No hay horarios para ese día.</div>';
      return;
    }
    let options = [];
    if (selectedMode === 'availability') {
      const uniqueTimes = [...new Set(currentDaySlots.map(slot => slot.label))];
      options = uniqueTimes.map(label => ({ label }));
    } else {
      options = currentDaySlots.map(slot => ({
        label: slot.label, start: slot.start,
        employee_id: slot.employee_id, employee_name: slot.employee_name
      }));
    }

    const groups = {
      manana: { label: 'Mañana', icon: TIME_ICON_SUN, items: [] },
      tarde:  { label: 'Tarde',  icon: TIME_ICON_SUN, items: [] },
      noche:  { label: 'Noche',  icon: TIME_ICON_MOON, items: [] },
    };
    options.forEach(option => {
      const hour = parseInt(option.label.split(':')[0], 10);
      if (hour < 13) groups.manana.items.push(option);
      else if (hour < 19) groups.tarde.items.push(option);
      else groups.noche.items.push(option);
    });

    Object.values(groups).forEach(group => {
      if (!group.items.length) return;
      const section = document.createElement('div');
      section.className = 'time-group';
      section.innerHTML = `<div class="time-group-label">${group.icon} ${group.label}</div>`;
      const row = document.createElement('div');
      row.className = 'd-flex flex-wrap gap-2';
      group.items.forEach(option => {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'btn btn-outline-secondary slot-btn';
        btn.textContent = option.label;
        btn.addEventListener('click', () => selectTime(option, btn));
        row.appendChild(btn);
      });
      section.appendChild(row);
      timeSlots.appendChild(section);
    });
  }

  const TIME_ICON_SUN = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4.5"/><path d="M12 2.5v2.5M12 19v2.5M4.9 4.9l1.8 1.8M17.3 17.3l1.8 1.8M2.5 12H5M19 12h2.5M4.9 19.1l1.8-1.8M17.3 6.7l1.8-1.8"/></svg>';
  const TIME_ICON_MOON = '<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 14.5A8.5 8.5 0 1110.3 4.2 6.8 6.8 0 0020 14.5z"/></svg>';

  function selectTime(option, buttonEl) {
    document.querySelectorAll('.slot-btn').forEach(x => x.classList.remove('active'));
    buttonEl.classList.add('active');
    selectedTimeLabel = option.label;
    timeStatus.textContent = option.label;

    if (selectedMode === 'availability') {
      const availableEmployees = currentDaySlots.filter(slot => slot.label === selectedTimeLabel);
      selectedSlot = null;
      renderEmployeeCards(availableEmployees, chooseEmployeeForMode);
      employeeStatus.textContent = 'Elegí un profesional';
      panels['employee'].classList.remove('d-none');
      showPanel('employee');
      updateStepper('employee', ['service','mode','date','time']);
      renderSummary('Ahora elegí el profesional para confirmar el turno.');
    } else {
      selectedSlot = option;
      attachEmployeeToSelectedTime(option.employee_id, option.employee_name, option.start);
    }
  }

  function attachEmployeeToSelectedTime(employeeId, employeeName = null, start = null) {
    const foundSlot = start
      ? currentDaySlots.find(slot => slot.start === start)
      : currentDaySlots.find(slot => slot.label === selectedTimeLabel && slot.employee_id === employeeId);

    if (!foundSlot) return;

    selectedSlot         = foundSlot;
    selectedEmployeeId   = foundSlot.employee_id;
    selectedEmployeeName = foundSlot.employee_name;

    employeeInput.value = foundSlot.employee_id;
    startInput.value    = foundSlot.start;
    employeeStatus.textContent = selectedEmployeeName;

    renderSummary('Revisá el resumen y completá tus datos para confirmar.');
    showConfirmScreen();
  }

  // Init
  fetch(`/api/${slug}/services`)
    .then(r => r.json())
    .then(data => {
      services = data;
      renderServices();
      resetSummary();
      updateStepper('service', []);
      if (preselectedServiceId) {
        const matched = services.find(s => s.id === preselectedServiceId);
        if (matched) applySelectedService(matched, { fromPreselected: true });
      }
    });

  document.getElementById('confirm-service-btn')?.addEventListener('click', () => {
    if (!pendingService) return;
    if (serviceModal) serviceModal.hide();
    applySelectedService(pendingService);
  });

  document.getElementById('prev-month')?.addEventListener('click', () => {
    currentMonth.setMonth(currentMonth.getMonth() - 1);
    renderMonth();
  });

  document.getElementById('next-month')?.addEventListener('click', () => {
    currentMonth.setMonth(currentMonth.getMonth() + 1);
    renderMonth();
  });

  backToFlowBtn?.addEventListener('click', () => showFlow());
  backToFlowBtnBottom?.addEventListener('click', () => showFlow());
  document.getElementById('slot-taken-back')?.addEventListener('click', (e) => {
    e.preventDefault();
    showFlow();
  });
  window.addEventListener('beforeunload', releaseSlotHold);
  document.getElementById('live-edit-service')?.addEventListener('click', (e) => {
    e.preventDefault();
    showFlow();
    showPanel('service');
    updateStepper('service', []);
  });
}
