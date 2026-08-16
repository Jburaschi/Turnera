(function () {
  function renumberScheduleRows(tbody) {
    tbody.querySelectorAll('tr.schedule-block-row').forEach((row, idx) => {
      const wd = row.querySelector('[data-field="weekday"]');
      const st = row.querySelector('[data-field="start"]');
      const en = row.querySelector('[data-field="end"]');
      const sv = row.querySelector('[data-field="services"]');
      if (wd) wd.name = 'block_' + idx + '_weekday';
      if (st) st.name = 'block_' + idx + '_start';
      if (en) en.name = 'block_' + idx + '_end';
      if (sv) sv.name = 'block_' + idx + '_service_ids';
    });
  }

  document.addEventListener('click', function (e) {
    const addBtn = e.target.closest('.schedule-add-row');
    if (addBtn) {
      const id = addBtn.getAttribute('data-schedule-tbody');
      const tbody = document.getElementById(id);
      if (!tbody) return;
      const first = tbody.querySelector('tr.schedule-block-row');
      if (!first) return;
      const neu = first.cloneNode(true);
      tbody.appendChild(neu);
      renumberScheduleRows(tbody);
      return;
    }

    const rm = e.target.closest('.schedule-row-remove');
    if (rm) {
      const row = rm.closest('tr.schedule-block-row');
      const tbody = row && row.closest('tbody');
      if (!tbody || tbody.querySelectorAll('tr.schedule-block-row').length <= 1) return;
      row.remove();
      renumberScheduleRows(tbody);
      return;
    }

    const rep = e.target.closest('.schedule-replicate-mon-fri');
    if (rep) {
      const id = rep.getAttribute('data-schedule-tbody');
      const tbody = document.getElementById(id);
      if (!tbody) return;
      const monRow = Array.from(tbody.querySelectorAll('tr.schedule-block-row')).find(function (r) {
        const sel = r.querySelector('[data-field="weekday"]');
        return sel && sel.value === '0';
      });
      if (!monRow) {
        window.alert('Necesitás al menos una fila con día Lunes para replicar el horario.');
        return;
      }
      ['1', '2', '3', '4'].forEach(function (wd) {
        const nr = monRow.cloneNode(true);
        const sel = nr.querySelector('[data-field="weekday"]');
        if (sel) sel.value = wd;
        tbody.appendChild(nr);
      });
      renumberScheduleRows(tbody);
    }
  });
})();
