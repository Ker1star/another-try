document.addEventListener('DOMContentLoaded', () => {
  const list = document.getElementById('orderItemsList');
  const totalEl = document.getElementById('orderTotal');
  const summary = document.getElementById('orderSummary');
  const summaryEmpty = document.getElementById('orderSummaryEmpty');
  const form = document.getElementById('orderForm');
  const submitButton = document.getElementById('submitOrder');
  const phoneInput = document.getElementById('phone');
  const consentCheck = document.getElementById('consentCheck');
  const messageBox = document.getElementById('orderMessage');
  const formTitle = document.getElementById('orderFormTitle');
  const pickupSelect = document.getElementById('pickupTime');
  const serviceInputs = form ? Array.from(form.querySelectorAll('input[name="serviceType"]')) : [];
  const cart = JSON.parse(localStorage.getItem('cart') || '[]');

  const latInput = document.getElementById('deliveryLat');
  const lonInput = document.getElementById('deliveryLon');
  const itemsTotalEl = document.getElementById('itemsTotal');
  const deliveryCostRow = document.getElementById('deliveryCostRow');
  const deliveryCostValue = document.getElementById('deliveryCostValue');
  const deliveryEtaEl = document.getElementById('deliveryEta');
  const zoneNote = document.getElementById('deliveryZoneNote');
  const mapBox = document.getElementById('deliveryMapBox');
  const mapImg = document.getElementById('deliveryMapImg');

  let itemsTotal = 0;
  let deliveryQuote = null;   // last /api/delivery/quote response, or null

  const getServiceType = () => {
    const checked = serviceInputs.find((input) => input.checked);
    return checked ? checked.value : 'delivery';
  };

  const updateTotals = () => {
    let grand = itemsTotal;
    if (getServiceType() === 'delivery' && deliveryQuote && deliveryQuote.found && deliveryQuote.inZone) {
      grand += Number(deliveryQuote.deliveryCost) || 0;
    }
    if (totalEl) totalEl.textContent = `${grand.toFixed(0)} ₽`;
  };

  // Block checkout only for definitive delivery problems; unknown/degraded states
  // pass through and are re-validated (and possibly degraded) on the server.
  const isDeliveryBlocked = () => {
    if (getServiceType() !== 'delivery') return false;
    const q = deliveryQuote;
    if (!q) return false;                                    // address not checked yet
    if (q.found) return q.inZone === false || !!q.belowMin;  // out of zone / below min
    return q.reason === 'not_found' || q.reason === 'incomplete';  // bad address
  };

  const updateSubmitState = () => {
    if (!submitButton) return;
    const hasCart = cart.length > 0;
    const consentOk = consentCheck ? consentCheck.checked : true;
    submitButton.disabled = !(hasCart && consentOk && !isDeliveryBlocked());
  };

  const setFieldRequired = (field, required) => {
    field.querySelectorAll('input, select, textarea').forEach((control) => {
      if (required) {
        control.setAttribute('required', 'required');
      } else {
        control.removeAttribute('required');
      }
    });
  };

  const applyServiceVisibility = () => {
    const service = getServiceType();
    document.querySelectorAll('[data-service]').forEach((node) => {
      const match = node.dataset.service === service;
      node.hidden = !match;
      if (node.classList.contains('field')) {
        setFieldRequired(node, match && node.querySelector('[name="apartment"], [name="pickupTime"]') === null);
        if (match && node.querySelector('[name="pickupTime"]')) {
          setFieldRequired(node, true);
        }
      }
    });
    if (formTitle) {
      formTitle.textContent = service === 'pickup' ? 'Самовывоз — выберите время' : 'Куда и кому привезти заказ';
    }
    if (submitButton) {
      submitButton.textContent = service === 'pickup' ? 'Оплатить и забрать' : 'Перейти к оплате';
    }
  };

  let pickupSlotsLoaded = false;
  const loadPickupSlots = async () => {
    if (!pickupSelect || pickupSlotsLoaded) return;
    try {
      const resp = await fetch('/api/pickup/slots', { headers: { Accept: 'application/json' } });
      if (!resp.ok) throw new Error('slots');
      const data = await resp.json();
      pickupSelect.innerHTML = '';
      if (!data.available || !data.slots.length) {
        const opt = document.createElement('option');
        opt.value = '';
        opt.textContent = data.available
          ? 'Сегодня уже не успеваем приготовить'
          : `Закрыто. Откроемся в ${data.opensAt}`;
        pickupSelect.appendChild(opt);
        pickupSelect.disabled = true;
      } else {
        const placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = 'Выберите время';
        pickupSelect.appendChild(placeholder);
        data.slots.forEach((slot) => {
          const opt = document.createElement('option');
          opt.value = slot.value;
          opt.textContent = slot.label;
          pickupSelect.appendChild(opt);
        });
        pickupSelect.disabled = false;
      }
      pickupSlotsLoaded = true;
    } catch (e) {
      pickupSelect.innerHTML = '<option value="">Не удалось загрузить время</option>';
    }
  };

  serviceInputs.forEach((input) => {
    input.addEventListener('change', () => {
      applyServiceVisibility();
      if (input.value === 'pickup') loadPickupSlots();
      try { onServiceChange(); } catch (e) {}
    });
  });
  applyServiceVisibility();

  const showMessage = (text, type = 'error') => {
    if (!messageBox) {
      return;
    }
    if (!text) {
      messageBox.hidden = true;
      messageBox.textContent = '';
      messageBox.classList.remove('message-box--error', 'message-box--success');
      return;
    }
    messageBox.hidden = false;
    messageBox.textContent = text;
    messageBox.classList.toggle('message-box--error', type === 'error');
    messageBox.classList.toggle('message-box--success', type === 'success');
  };

  const renderSummary = () => {
    if (!list || !totalEl || !submitButton) {
      return;
    }

    list.innerHTML = '';

    if (!cart.length) {
      summary?.setAttribute('hidden', '');
      summaryEmpty?.removeAttribute('hidden');
      submitButton.disabled = true;
      showMessage('Корзина пустая. Вернитесь в меню доставки и добавьте блюда.', 'error');
      return;
    }

    summary?.removeAttribute('hidden');
    summaryEmpty?.setAttribute('hidden', '');

    let total = 0;
    cart.forEach(item => {
      const qty = item.qty || 1;
      const amount = (Number(item.price) || 0) * qty;
      total += amount;

      const row = document.createElement('li');
      const title = document.createElement('span');
      title.textContent = `${item.name} × ${qty}`;
      const price = document.createElement('strong');
      price.textContent = `${amount.toFixed(0)} ₽`;
      row.append(title, price);
      list.appendChild(row);
    });

    itemsTotal = total;
    if (itemsTotalEl) itemsTotalEl.textContent = `${total.toFixed(0)} ₽`;
    updateTotals();
    updateSubmitState();
  };

  phoneInput?.addEventListener('input', () => {
    phoneInput.value = phoneInput.value.replace(/[^0-9+()\-\s]/g, '').slice(0, 22);
  });

  // --- Persisted order status (localStorage, no auth needed) ---
  // Lets a customer who closed the tab mid-payment (or right after) come back
  // to /order later and still see what happened to their last order.
  const ORDER_TRACKING_KEY = 'marta_last_order';
  const ORDER_TRACKING_PENDING_RESUME_MS = 5 * 60 * 1000; // still-pending order: auto-resume polling
  const ORDER_TRACKING_RESOLVED_SHOW_MS = 10 * 60 * 1000; // already-resolved order: show once more

  const saveOrderTracking = (data) => {
    try { localStorage.setItem(ORDER_TRACKING_KEY, JSON.stringify(data)); } catch (e) {}
  };
  const loadOrderTracking = () => {
    try { return JSON.parse(localStorage.getItem(ORDER_TRACKING_KEY) || 'null'); } catch (e) { return null; }
  };
  const clearOrderTracking = () => {
    try { localStorage.removeItem(ORDER_TRACKING_KEY); } catch (e) {}
  };

  const PHONE_HTML = '<a href="tel:+78212291247">+7 (8212) 29-12-47</a>';
  const ACTIONS_DEFAULT = '<a href="/" class="button">На главную</a><a href="/menu" class="button-secondary">Посмотреть меню</a>';

  const successState = (orderNumber) => ({
    icon: '✓',
    title: orderNumber ? `Заказ №${orderNumber} принят` : 'Заказ принят',
    text: 'Заказ передан в систему ресторана. Чек придёт на электронную почту.',
  });
  const failedState = () => ({
    cls: 'payment-result--warning',
    icon: '!',
    title: 'Не удалось передать заказ',
    text: `Оплата прошла, но мы не смогли передать заказ в систему ресторана. Позвоните: ${PHONE_HTML} — примем заказ вручную и сразу подтвердим.`,
    actions: `<a href="tel:+78212291247" class="button">Позвонить</a><a href="/" class="button-secondary">На главную</a>`,
  });

  // Shows the payment-result section and, unless an immediate status is given,
  // polls /api/payments/{id}/status until it resolves (or times out).
  const runPaymentStatusFlow = (trackingId, { immediateStatus, immediateOrderNumber } = {}) => {
    const heroSection = document.querySelector('.page-hero');
    const formSection = document.getElementById('orderFormSection');
    const resultSection = document.getElementById('paymentResult');
    const iconEl = resultSection?.querySelector('[data-result-icon]');
    const titleEl = resultSection?.querySelector('[data-result-title]');
    const textEl = resultSection?.querySelector('[data-result-text]');
    const actionsEl = resultSection?.querySelector('.payment-result-actions');

    if (heroSection) heroSection.hidden = true;
    if (formSection) formSection.hidden = true;
    if (resultSection) resultSection.hidden = false;
    window.scrollTo({ top: 0, behavior: 'auto' });

    const setState = (state) => {
      if (!resultSection) return;
      resultSection.classList.remove('payment-result--error', 'payment-result--warning', 'payment-result--processing');
      if (state.cls) resultSection.classList.add(state.cls);
      if (iconEl) iconEl.innerHTML = state.icon;
      if (titleEl) titleEl.textContent = state.title;
      if (textEl) textEl.innerHTML = state.text;
      if (actionsEl) actionsEl.innerHTML = state.actions ?? ACTIONS_DEFAULT;
    };

    if (immediateStatus === 'paid') {
      setState(successState(immediateOrderNumber));
      return;
    }
    if (immediateStatus === 'failed') {
      setState(failedState());
      return;
    }
    if (immediateStatus === 'error') {
      setState({
        cls: 'payment-result--error',
        icon: '!',
        title: 'Оплата не прошла',
        text: `Платёж не был завершён. Деньги не списались. Попробуйте ещё раз или позвоните: ${PHONE_HTML}`,
      });
      return;
    }

    setState({
      cls: 'payment-result--processing',
      icon: '<span class="payment-spinner" aria-hidden="true"></span>',
      title: 'Проверяем оплату…',
      text: 'Подтверждаем платёж и передаём заказ в систему ресторана. Несколько секунд.',
      actions: '',
    });

    const startTime = Date.now();
    const POLL_INTERVAL = 2000;
    const POLL_TIMEOUT = 30000;
    let stopped = false;

    const stop = () => { stopped = true; };

    const poll = async () => {
      if (stopped) return;
      try {
        const resp = await fetch(`/api/payments/${encodeURIComponent(trackingId)}/status`);
        if (resp.ok) {
          const data = await resp.json();
          if (data.status === 'paid') {
            saveOrderTracking({ trackingId, status: 'paid', orderNumber: data.orderNumber, resolvedAt: Date.now() });
            setState(successState(data.orderNumber));
            stop();
            return;
          }
          if (data.status === 'failed') {
            saveOrderTracking({ trackingId, status: 'failed', resolvedAt: Date.now() });
            setState(failedState());
            stop();
            return;
          }
        }
      } catch (e) {}

      if (Date.now() - startTime > POLL_TIMEOUT) {
        setState({
          icon: '✓',
          title: 'Заказ оплачен',
          text: `Оплата прошла. Передаём заказ в систему ресторана — может занять минуту. Если есть вопросы: ${PHONE_HTML}`,
        });
        stop();
        return;
      }

      setTimeout(poll, POLL_INTERVAL);
    };

    setTimeout(poll, 500);
  };

  // Handle return from YooKassa payment page
  const params = new URLSearchParams(window.location.search);
  const paymentStatus = params.get('payment');
  const trackingId = params.get('id');

  if (paymentStatus === 'success' || paymentStatus === 'error') {
    if (paymentStatus === 'success') {
      localStorage.removeItem('cart');
    }

    if (paymentStatus === 'error') {
      clearOrderTracking();
      runPaymentStatusFlow(null, { immediateStatus: 'error' });
      return;
    }

    if (!trackingId) {
      runPaymentStatusFlow(null, { immediateStatus: 'paid' });
      return;
    }

    runPaymentStatusFlow(trackingId);
    return;
  }

  // Returning visitor with no payment params in the URL: resume tracking the
  // last order from localStorage instead of leaving them guessing.
  const storedOrder = loadOrderTracking();
  if (storedOrder && storedOrder.trackingId) {
    const age = Date.now() - (storedOrder.createdAt || 0);
    if (storedOrder.status && storedOrder.status !== 'pending') {
      const stillFresh = Date.now() - (storedOrder.resolvedAt || 0) < ORDER_TRACKING_RESOLVED_SHOW_MS;
      clearOrderTracking();
      if (stillFresh) {
        runPaymentStatusFlow(storedOrder.trackingId, {
          immediateStatus: storedOrder.status,
          immediateOrderNumber: storedOrder.orderNumber,
        });
        return;
      }
    } else if (age < ORDER_TRACKING_PENDING_RESUME_MS) {
      runPaymentStatusFlow(storedOrder.trackingId);
      return;
    } else {
      clearOrderTracking();
    }
  }

  renderSummary();

  // --- Static map + server-side delivery-zone quote ---
  const QUOTE_DEBOUNCE_MS = 600;
  let quoteTimer = null;

  const setZoneNote = (text, kind) => {
    if (!zoneNote) return;
    zoneNote.textContent = text || '';
    zoneNote.classList.toggle('is-error', kind === 'error');
    zoneNote.classList.toggle('is-ok', kind === 'ok');
  };

  const cartItemsPayload = () => cart.map((item) => ({ id: item.id, qty: item.qty || 1 }));

  const addressParts = () => ({
    city: (form.city && form.city.value.trim()) || '',
    street: (form.street && form.street.value.trim()) || '',
    house: (form.house && form.house.value.trim()) || '',
  });

  const showStaticMap = (lat, lon) => {
    if (!mapBox || !mapImg) return;
    const key = mapBox.dataset.staticKey;
    if (!key) { mapBox.hidden = true; return; }
    const ll = `${lon},${lat}`;
    mapImg.onerror = () => { mapBox.hidden = true; };
    mapImg.src = `https://static-maps.yandex.ru/v1?ll=${ll}&z=16&size=450,280&pt=${ll},pm2rdm&lang=ru_RU&apikey=${encodeURIComponent(key)}`;
    mapBox.hidden = false;
  };

  const renderQuote = (q) => {
    deliveryQuote = q;
    if (getServiceType() !== 'delivery') return;

    if (q.found) {
      latInput.value = q.lat;
      lonInput.value = q.lon;
      showStaticMap(q.lat, q.lon);
      if (!q.inZone) {
        if (deliveryCostRow) deliveryCostRow.hidden = true;
        setZoneNote('Адрес вне зоны доставки. Доступен только самовывоз.', 'error');
      } else if (q.belowMin) {
        if (deliveryCostRow) deliveryCostRow.hidden = true;
        setZoneNote(`Минимальный заказ для доставки — ${Number(q.minOrder).toFixed(0)} ₽.`, 'error');
      } else {
        if (deliveryCostRow) deliveryCostRow.hidden = false;
        if (deliveryCostValue) {
          deliveryCostValue.textContent = q.deliveryCost > 0 ? `${Number(q.deliveryCost).toFixed(0)} ₽` : 'Бесплатно';
        }
        if (deliveryEtaEl) deliveryEtaEl.textContent = q.etaMinutes ? `~${q.etaMinutes} мин` : '';
        const freeHint = (q.deliveryCost > 0 && q.freeFrom) ? ` Бесплатно от ${Number(q.freeFrom).toFixed(0)} ₽.` : '';
        setZoneNote(`Доставка в зону «${q.zoneName}».${freeHint}`, 'ok');
      }
    } else {
      latInput.value = '';
      lonInput.value = '';
      if (mapBox) mapBox.hidden = true;
      if (deliveryCostRow) deliveryCostRow.hidden = true;
      if (q.reason === 'no_geocoder') {
        setZoneNote('Стоимость доставки уточнит ресторан после оформления.', null);
      } else if (q.reason === 'incomplete') {
        setZoneNote('Заполните улицу и дом — проверим зону доставки.', null);
      } else {
        setZoneNote(q.error || 'Не удалось определить адрес. Проверьте улицу и дом.', 'error');
      }
    }
    updateTotals();
    updateSubmitState();
  };

  const requestQuote = async () => {
    if (!cart.length) return;
    const address = addressParts();
    if (!address.street || !address.house) {
      renderQuote({ found: false, reason: 'incomplete' });
      return;
    }
    try {
      const resp = await fetch('/api/delivery/quote', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address, items: cartItemsPayload() }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) { setZoneNote(data.error || 'Не удалось рассчитать доставку.', 'error'); return; }
      renderQuote(data);
    } catch (e) {
      setZoneNote('Не удалось рассчитать доставку. Проверьте адрес или позвоните нам.', 'error');
    }
  };

  const scheduleQuote = () => {
    clearTimeout(quoteTimer);
    quoteTimer = setTimeout(requestQuote, QUOTE_DEBOUNCE_MS);
  };

  // Quote triggers: house drives the debounced quote; "change" on street/house finalizes.
  if (form.house) form.house.addEventListener('input', scheduleQuote);
  ['street', 'house'].forEach((name) => {
    if (form[name]) form[name].addEventListener('change', requestQuote);
  });

  // --- Street autocomplete via /api/suggest ---
  const suggestBox = document.getElementById('streetSuggest');
  let suggestTimer = null;

  // "Первомайская улица, 115" -> { street: "Первомайская улица", house: "115" }
  // "Первомайская улица"      -> { street: "Первомайская улица", house: null }
  const splitStreetHouse = (title) => {
    const m = title.match(/^(.+),\s*(\d[\d/\-\sА-Яа-яA-Za-z]*)\s*$/);
    if (m) return { street: m[1].trim(), house: m[2].trim() };
    return { street: title.trim(), house: null };
  };

  const hideSuggest = () => {
    if (!suggestBox) return;
    suggestBox.hidden = true;
    suggestBox.innerHTML = '';
  };

  const renderSuggestions = (items) => {
    if (!suggestBox) return;
    if (!items.length) { hideSuggest(); return; }
    suggestBox.innerHTML = '';
    items.forEach((it) => {
      const li = document.createElement('li');
      li.textContent = it.title;
      if (it.subtitle) {
        const sub = document.createElement('small');
        sub.textContent = it.subtitle;
        li.appendChild(sub);
      }
      li.addEventListener('mousedown', (e) => {
        e.preventDefault();   // fire before the input's blur hides the list
        const parsed = splitStreetHouse(it.title);
        if (form.street) form.street.value = parsed.street;
        if (parsed.house && form.house) form.house.value = parsed.house;
        hideSuggest();
        if (form.house && !parsed.house) form.house.focus();
        requestQuote();
      });
      suggestBox.appendChild(li);
    });
    suggestBox.hidden = false;
  };

  const fetchSuggest = async () => {
    const q = (form.street && form.street.value.trim()) || '';
    if (q.length < 1) { hideSuggest(); return; }
    try {
      const resp = await fetch(`/api/suggest?q=${encodeURIComponent(q)}`);
      if (!resp.ok) { hideSuggest(); return; }
      renderSuggestions(await resp.json());
    } catch (e) {
      hideSuggest();
    }
  };

  if (form.street) {
    form.street.addEventListener('input', () => {
      clearTimeout(suggestTimer);
      suggestTimer = setTimeout(fetchSuggest, 250);
    });
    form.street.addEventListener('blur', () => setTimeout(hideSuggest, 150));
  }

  const onServiceChange = () => {
    const isDelivery = getServiceType() === 'delivery';
    if (!isDelivery && deliveryCostRow) deliveryCostRow.hidden = true;
    if (isDelivery) {
      if (deliveryQuote) renderQuote(deliveryQuote); else requestQuote();
    }
    updateTotals();
    updateSubmitState();
  };

  if (getServiceType() === 'delivery') requestQuote();

  consentCheck?.addEventListener('change', () => {
    updateSubmitState();
  });

  form?.addEventListener('submit', async event => {
    event.preventDefault();
    if (!cart.length) {
      showMessage('Корзина пустая.', 'error');
      return;
    }
    if (consentCheck && !consentCheck.checked) {
      showMessage('Подтвердите согласие на обработку персональных данных.', 'error');
      return;
    }

    showMessage('');
    submitButton.disabled = true;
    submitButton.textContent = 'Создаём платёж...';

    const service = getServiceType();
    if (service === 'pickup' && !pickupSelect?.value) {
      showMessage('Выберите время самовывоза.', 'error');
      submitButton.disabled = false;
      submitButton.textContent = 'Оплатить и забрать';
      return;
    }

    const payload = {
      serviceType: service,
      customerName: form.customerName.value.trim(),
      phone: form.phone.value.trim(),
      email: form.email.value.trim(),
      comment: form.comment.value.trim(),
      items: cart.map(item => ({
        id: item.id,
        hierarchicalId: item.hierarchicalId || item.id,
        prestoId: item.prestoId ?? null,
        externalId: item.externalId ?? null,
        nomNumber: item.nomNumber ?? null,
        name: item.name,
        price: Number(item.price) || 0,
        qty: item.qty || 1,
      })),
    };

    if (service === 'delivery') {
      payload.address = {
        city: form.city.value.trim(),
        street: form.street.value.trim(),
        house: form.house.value.trim(),
        apartment: form.apartment.value.trim(),
      };
      if (latInput?.value && lonInput?.value) {
        payload.lat = Number(latInput.value);
        payload.lon = Number(lonInput.value);
      }
    } else {
      payload.pickupTime = pickupSelect.value;
    }

    try {
      const response = await fetch('/api/payments', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(result.error || 'Не удалось создать платёж.');
      }

      if (!result.confirmationUrl) {
        throw new Error('Сервер не вернул ссылку для оплаты.');
      }

      if (result.trackingId) {
        saveOrderTracking({ trackingId: result.trackingId, status: 'pending', createdAt: Date.now() });
      }

      window.location.href = result.confirmationUrl;
    } catch (error) {
      submitButton.disabled = false;
      submitButton.textContent = 'Перейти к оплате';
      showMessage(error.message || 'Не удалось создать платёж.', 'error');
    }
  });
});
