document.addEventListener('DOMContentLoaded', () => {
  const editor = document.getElementById('menuEditor');
  const statusEl = document.getElementById('status');
  const saveBtn = document.getElementById('saveBtn');
  const ordersLog = document.getElementById('ordersLog');

  let state = [];  // [{id, name, hidden, items: [{id, name, hidden, price}]}]
  let currentMode = 'restaurant';

  const escapeHtml = (s) => (s || '').replace(/[&<>"]/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]
  ));

  const setStatus = (msg, kind) => {
    statusEl.textContent = msg || '';
    statusEl.className = kind || '';
  };

  const move = (arr, i, dir) => {
    const j = i + dir;
    if (j < 0 || j >= arr.length) return;
    [arr[i], arr[j]] = [arr[j], arr[i]];
  };

  const render = () => {
    editor.innerHTML = '';
    state.forEach((cat, ci) => {
      const catEl = document.createElement('div');
      catEl.className = 'cat' + (cat.hidden ? ' is-hidden' : '');
      const head = document.createElement('div');
      head.className = 'cat-head';
      head.innerHTML = `
        <span class="arrows">
          <button data-act="cat-up" data-ci="${ci}">↑</button>
          <button data-act="cat-down" data-ci="${ci}">↓</button>
        </span>
        <strong style="flex:1">${escapeHtml(cat.name)}</strong>
        <label class="hide"><input type="checkbox" data-act="cat-hide" data-ci="${ci}" ${cat.hidden ? 'checked' : ''}> скрыть</label>
      `;
      catEl.appendChild(head);
      cat.items.forEach((it, ii) => {
        const itEl = document.createElement('div');
        itEl.className = 'item' + (it.hidden ? ' is-hidden' : '');
        itEl.innerHTML = `
          <span class="arrows">
            <button data-act="item-up" data-ci="${ci}" data-ii="${ii}">↑</button>
            <button data-act="item-down" data-ci="${ci}" data-ii="${ii}">↓</button>
          </span>
          <span class="name">${escapeHtml(it.name)}</span>
          <span class="price">${Number(it.price).toFixed(0)} ₽</span>
          <label class="hide"><input type="checkbox" data-act="item-hide" data-ci="${ci}" data-ii="${ii}" ${it.hidden ? 'checked' : ''}> скрыть</label>
        `;
        catEl.appendChild(itEl);
      });
      editor.appendChild(catEl);
    });
  };

  editor.addEventListener('click', (e) => {
    const btn = e.target.closest('button[data-act]');
    if (!btn) return;
    const ci = Number(btn.dataset.ci);
    const ii = Number(btn.dataset.ii);
    const act = btn.dataset.act;
    if (act === 'cat-up') move(state, ci, -1);
    else if (act === 'cat-down') move(state, ci, 1);
    else if (act === 'item-up') move(state[ci].items, ii, -1);
    else if (act === 'item-down') move(state[ci].items, ii, 1);
    render();
  });

  editor.addEventListener('change', (e) => {
    const cb = e.target.closest('input[data-act]');
    if (!cb) return;
    const ci = Number(cb.dataset.ci);
    const ii = Number(cb.dataset.ii);
    if (cb.dataset.act === 'cat-hide') state[ci].hidden = cb.checked;
    else if (cb.dataset.act === 'item-hide') state[ci].items[ii].hidden = cb.checked;
    render();
  });

  saveBtn?.addEventListener('click', async () => {
    setStatus('Сохраняю…');
    try {
      const resp = await fetch('/api/admin/save', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ categories: state }),
      });
      if (!resp.ok) throw new Error('save failed');
      setStatus('Сохранено ✓ (изменения уже на сайте)', 'ok');
    } catch (e) {
      setStatus('Ошибка сохранения — попробуйте ещё раз', 'err');
    }
  });

  const loadMenu = async () => {
    editor.textContent = 'Загрузка…';
    try {
      const resp = await fetch(`/api/admin/menu?mode=${encodeURIComponent(currentMode)}`);
      if (!resp.ok) { editor.textContent = 'Сессия истекла — обновите страницу и войдите заново.'; return; }
      const data = await resp.json();
      state = data.categories || [];
      render();
    } catch (e) {
      editor.textContent = 'Не удалось загрузить меню.';
    }
  };

  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      if (tab.classList.contains('is-active')) return;
      document.querySelectorAll('.tab').forEach((t) => t.classList.remove('is-active'));
      tab.classList.add('is-active');
      currentMode = tab.dataset.mode;
      setStatus('');
      loadMenu();
    });
  });

  const loadOrders = async () => {
    try {
      const resp = await fetch('/api/admin/orders');
      if (!resp.ok) { ordersLog.textContent = '—'; return; }
      const data = await resp.json();
      const rows = (data.orders || []).map((o) =>
        `<tr><td>#${o.id}</td><td>${escapeHtml(o.status || '')}</td><td>${escapeHtml(o.service || '')}</td>` +
        `<td>${escapeHtml(o.name || '')}</td><td>${escapeHtml(o.phone || '')}</td>` +
        `<td>${escapeHtml(o.address || '')}</td><td>${escapeHtml((o.created || '').replace('T', ' ').slice(0, 16))}</td></tr>`
      ).join('');
      ordersLog.innerHTML = rows
        ? `<table><thead><tr><th>#</th><th>статус</th><th>тип</th><th>имя</th><th>телефон</th><th>адрес</th><th>время</th></tr></thead><tbody>${rows}</tbody></table>`
        : 'Заказов пока нет.';
    } catch (e) {
      ordersLog.textContent = '—';
    }
  };

  // --- Промокоды ---
  const promoForm = document.getElementById('promoForm');
  const promoStatus = document.getElementById('promoStatus');
  const promoList = document.getElementById('promoList');

  const setPromoStatus = (msg, kind) => {
    if (!promoStatus) return;
    promoStatus.textContent = msg || '';
    promoStatus.className = kind || '';
  };

  const renderPromoList = (promoCodes) => {
    if (!promoList) return;
    if (!promoCodes.length) {
      promoList.textContent = 'Промокодов пока нет.';
      return;
    }
    const rows = promoCodes.map((p) => {
      const value = p.discountType === 'percent' ? `${p.discountValue}%` : `${p.discountValue} ₽`;
      const min = p.minOrderAmount != null ? `от ${p.minOrderAmount} ₽` : '—';
      const until = p.validUntil ? p.validUntil.slice(0, 10) : '—';
      const usage = `${p.timesUsed}${p.usageLimit != null ? ` / ${p.usageLimit}` : ''}`;
      return `<tr>
        <td><strong>${escapeHtml(p.code)}</strong></td>
        <td>${value}</td>
        <td>${min}</td>
        <td>${until}</td>
        <td>${usage}</td>
        <td>${p.maxUsesPerCustomer}× на клиента</td>
        <td><button class="promo-toggle ${p.isActive ? 'is-active' : 'is-off'}" data-id="${p.id}">${p.isActive ? 'активен' : 'выключен'}</button></td>
      </tr>`;
    }).join('');
    promoList.innerHTML = `<table><thead><tr>
      <th>код</th><th>скидка</th><th>мин. сумма</th><th>до</th><th>использован</th><th>лимит</th><th></th>
    </tr></thead><tbody>${rows}</tbody></table>`;
  };

  const loadPromoCodes = async () => {
    try {
      const resp = await fetch('/api/admin/promo');
      if (!resp.ok) { promoList.textContent = '—'; return; }
      const data = await resp.json();
      renderPromoList(data.promoCodes || []);
    } catch (e) {
      promoList.textContent = '—';
    }
  };

  promoForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    setPromoStatus('Создаю…');
    const body = {
      code: document.getElementById('promoCodeInput').value.trim(),
      discountType: document.getElementById('promoTypeInput').value,
      discountValue: document.getElementById('promoValueInput').value,
      minOrderAmount: document.getElementById('promoMinOrderInput').value || null,
      validUntil: document.getElementById('promoValidUntilInput').value || null,
      usageLimit: document.getElementById('promoUsageLimitInput').value || null,
      maxUsesPerCustomer: document.getElementById('promoMaxPerCustomerInput').value || 1,
    };
    try {
      const resp = await fetch('/api/admin/promo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const result = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(result.error || 'Не удалось создать промокод.');
      setPromoStatus(`Промокод ${result.promoCode.code} создан ✓`, 'ok');
      promoForm.reset();
      document.getElementById('promoMaxPerCustomerInput').value = 1;
      loadPromoCodes();
    } catch (err) {
      setPromoStatus(err.message, 'err');
    }
  });

  promoList?.addEventListener('click', async (e) => {
    const btn = e.target.closest('button.promo-toggle');
    if (!btn) return;
    btn.disabled = true;
    try {
      const resp = await fetch(`/api/admin/promo/${btn.dataset.id}/toggle`, { method: 'POST' });
      if (!resp.ok) throw new Error();
      loadPromoCodes();
    } catch (e) {
      setPromoStatus('Не удалось переключить промокод.', 'err');
      btn.disabled = false;
    }
  });

  loadMenu();
  loadOrders();
  loadPromoCodes();
});
