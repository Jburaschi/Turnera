(function () {
  function esc(s) {
    if (!s) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function fillEmployeeSelects(serviceId, selectedId) {
    const list = (window.TURNEX_EMPLOYEES_BY_SERVICE && window.TURNEX_EMPLOYEES_BY_SERVICE[serviceId]) || [];
    document.querySelectorAll('.manual-employee-sync').forEach(function (sel) {
      sel.innerHTML = '<option value="">Elegir</option>' + list.map(function (p) {
        return '<option value="' + p.id + '">' + esc(p.name) + '</option>';
      }).join('');
      if (selectedId != null && String(selectedId)) {
        sel.value = String(selectedId);
      }
    });
  }

  function syncServiceFrom(el) {
    const v = el.value;
    document.querySelectorAll('.manual-service-sync').forEach(function (o) {
      if (o !== el) o.value = v;
    });
    fillEmployeeSelects(v, null);
  }

  document.addEventListener('DOMContentLoaded', function () {
    const toggleBtn = document.getElementById('btn-toggle-manual-booking');
    const panel = document.getElementById('manual-booking-panel');
    if (toggleBtn && panel) {
      function updateToggleLabel() {
        const hidden = panel.classList.contains('d-none');
        toggleBtn.textContent = hidden ? 'Crear turno' : 'Ocultar creación de turno';
        toggleBtn.setAttribute('aria-expanded', hidden ? 'false' : 'true');
      }
      toggleBtn.addEventListener('click', function () {
        panel.classList.toggle('d-none');
        updateToggleLabel();
      });
      updateToggleLabel();
    }

    document.querySelectorAll('.manual-service-sync').forEach(function (sel) {
      sel.addEventListener('change', function () {
        syncServiceFrom(sel);
      });
    });

    const firstSvc = document.querySelector('.manual-service-sync');
    if (firstSvc && firstSvc.value && window.TURNEX_EMPLOYEES_BY_SERVICE) {
      fillEmployeeSelects(firstSvc.value, window.TURNEX_SELECTED_MANUAL_EMPLOYEE_ID);
    }

    const custSel = document.getElementById('manual_customer_id_sel');
    const filt = document.getElementById('manual-customer-filter');
    if (custSel && filt) {
      filt.addEventListener('input', function () {
        const q = filt.value.trim().toLowerCase();
        custSel.querySelectorAll('option').forEach(function (opt) {
          if (!opt.value) {
            opt.hidden = false;
            return;
          }
          const t = (opt.textContent || '').toLowerCase();
          opt.hidden = q.length > 0 && !t.includes(q);
        });
      });

      custSel.addEventListener('change', function () {
        const opt = custSel.selectedOptions[0];
        if (!opt || !opt.value) return;
        const gname = document.getElementById('manual_guest_name');
        const gphone = document.getElementById('manual_guest_phone');
        const gemail = document.getElementById('manual_guest_email');
        const gdni = document.getElementById('manual_guest_dni');
        if (gname) gname.value = opt.getAttribute('data-name') || '';
        if (gphone) gphone.value = opt.getAttribute('data-phone') || '';
        if (gemail) gemail.value = opt.getAttribute('data-email') || '';
        if (gdni) gdni.value = opt.getAttribute('data-dni') || '';
      });
    }
  });
})();
