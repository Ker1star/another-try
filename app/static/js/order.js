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

  let itemsTotal = 0;
  let deliveryQuote = null;   // last /api/delivery/quote result, or null
  let mapAvailable = false;   // false until the Yandex map initializes (graceful fallback)

  const getServiceType = () => {
    const checked = serviceInputs.find((input) => input.checked);
    return checked ? checked.value : 'delivery';
  };

  const updateTotals = () => {
    let grand = itemsTotal;
    if (getServiceType() === 'delivery' && deliveryQuote && deliveryQuote.inZone) {
      grand += Number(deliveryQuote.deliveryCost) || 0;
    }
    if (totalEl) totalEl.textContent = `${grand.toFixed(0)} ₽`;
  };

  const updateSubmitState = () => {
    if (!submitButton) return;
    const hasCart = cart.length > 0;
    const consentOk = consentCheck ? consentCheck.checked : true;
    let ready = hasCart && consentOk;
    // Gate delivery on a valid in-zone quote — but only when the map actually loaded,
    // so an outage of Yandex never blocks orders (server re-validates anyway).
    if (getServiceType() === 'delivery' && mapAvailable) {
      ready = ready && !!deliveryQuote && deliveryQuote.inZone && !deliveryQuote.belowMin && !!(latInput && latInput.value);
    }
    submitButton.disabled = !ready;
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

  // Handle return from YooKassa payment page
  const params = new URLSearchParams(window.location.search);
  const paymentStatus = params.get('payment');
  const trackingId = params.get('id');

  if (paymentStatus === 'success' || paymentStatus === 'error') {
    const heroSection = document.querySelector('.page-hero');
    const formSection = document.getElementById('orderFormSection');
    const resultSection = document.getElementById('paymentResult');
    const iconEl = resultSection?.querySelector('[data-result-icon]');
    const titleEl = resultSection?.querySelector('[data-result-title]');
    const textEl = resultSection?.querySelector('[data-result-text]');
    const actionsEl = resultSection?.querySelector('.payment-result-actions');

    if (paymentStatus === 'success') {
      localStorage.removeItem('cart');
    }

    if (heroSection) heroSection.hidden = true;
    if (formSection) formSection.hidden = true;
    if (resultSection) resultSection.hidden = false;
    window.scrollTo({ top: 0, behavior: 'auto' });

    const PHONE_HTML = '<a href="tel:+78212291247">+7 (8212) 29-12-47</a>';
    const ACTIONS_DEFAULT = '<a href="/" class="button">На главную</a><a href="/menu" class="button-secondary">Посмотреть меню</a>';

    const setState = (state) => {
      if (!resultSection) return;
      resultSection.classList.remove('payment-result--error', 'payment-result--warning', 'payment-result--processing');
      if (state.cls) resultSection.classList.add(state.cls);
      if (iconEl) iconEl.innerHTML = state.icon;
      if (titleEl) titleEl.textContent = state.title;
      if (textEl) textEl.innerHTML = state.text;
      if (actionsEl) actionsEl.innerHTML = state.actions ?? ACTIONS_DEFAULT;
    };

    if (paymentStatus === 'error') {
      setState({
        cls: 'payment-result--error',
        icon: '!',
        title: 'Оплата не прошла',
        text: `Платёж не был завершён. Деньги не списались. Попробуйте ещё раз или позвоните: ${PHONE_HTML}`,
      });
      return;
    }

    if (!trackingId) {
      setState({
        icon: '✓',
        title: 'Заказ принят',
        text: 'Заказ передан в систему ресторана. Чек придёт на электронную почту.',
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
            setState({
              icon: '✓',
              title: 'Заказ принят',
              text: 'Заказ передан в систему ресторана. Чек придёт на электронную почту.',
            });
            stop();
            return;
          }
          if (data.status === 'failed') {
            setState({
              cls: 'payment-result--warning',
              icon: '!',
              title: 'Не удалось передать заказ',
              text: `Оплата прошла, но мы не смогли передать заказ в систему ресторана. Позвоните: ${PHONE_HTML} — примем заказ вручную и сразу подтвердим.`,
              actions: `<a href="tel:+78212291247" class="button">Позвонить</a><a href="/" class="button-secondary">На главную</a>`,
            });
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
    return;
  }

  renderSummary();

  // --- Yandex map + delivery-zone quote ---
  const SYK_CENTER = [61.6688, 50.8364];
  const SYK_BOUNDS = [[61.60, 50.70], [61.72, 50.95]];
  let deliveryMap = null;
  let placemark = null;

  const setZoneNote = (text, kind) => {
    if (!zoneNote) return;
    zoneNote.textContent = text || '';
    zoneNote.classList.toggle('is-error', kind === 'error');
    zoneNote.classList.toggle('is-ok', kind === 'ok');
  };

  const cartItemsPayload = () => cart.map((item) => ({ id: item.id, qty: item.qty || 1 }));

  const renderDeliveryQuote = (q) => {
    deliveryQuote = q;
    if (getServiceType() !== 'delivery') return;
    if (!q || !q.inZone) {
      if (deliveryCostRow) deliveryCostRow.hidden = true;
      setZoneNote('Адрес вне зоны доставки. Доступен только самовывоз.', 'error');
    } else {
      if (deliveryCostRow) deliveryCostRow.hidden = false;
      if (deliveryCostValue) {
        deliveryCostValue.textContent = q.deliveryCost > 0 ? `${Number(q.deliveryCost).toFixed(0)} ₽` : 'Бесплатно';
      }
      if (deliveryEtaEl) deliveryEtaEl.textContent = q.etaMinutes ? `~${q.etaMinutes} мин` : '';
      if (q.belowMin) {
        setZoneNote(`Минимальный заказ для доставки — ${Number(q.minOrder).toFixed(0)} ₽.`, 'error');
      } else {
        const freeHint = (q.deliveryCost > 0 && q.freeFrom) ? ` Бесплатно от ${Number(q.freeFrom).toFixed(0)} ₽.` : '';
        setZoneNote(`Доставка в зону «${q.zoneName}».${freeHint}`, 'ok');
      }
    }
    updateTotals();
    updateSubmitState();
  };

  const requestQuote = async (coords) => {
    if (!coords || !cart.length) return;
    try {
      const resp = await fetch('/api/delivery/quote', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lat: coords[0], lon: coords[1], items: cartItemsPayload() }),
      });
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) { setZoneNote(data.error || 'Не удалось рассчитать доставку.', 'error'); return; }
      renderDeliveryQuote(data);
    } catch (e) {
      setZoneNote('Не удалось рассчитать доставку. Проверьте адрес или позвоните нам.', 'error');
    }
  };

  const fillAddressFromGeoObject = (obj) => {
    try {
      const street = obj.getThoroughfare && obj.getThoroughfare();
      const house = obj.getPremiseNumber && obj.getPremiseNumber();
      const localities = obj.getLocalities && obj.getLocalities();
      if (street && form.street) form.street.value = street;
      if (house && form.house) form.house.value = house;
      if (localities && localities.length && form.city) form.city.value = localities[0];
    } catch (e) {}
  };

  const setPoint = (coords) => {
    latInput.value = coords[0];
    lonInput.value = coords[1];
    if (!placemark) {
      placemark = new ymaps.Placemark(coords, {}, { draggable: true });
      placemark.events.add('dragend', () => {
        const c = placemark.geometry.getCoordinates();
        latInput.value = c[0];
        lonInput.value = c[1];
        ymaps.geocode(c, { results: 1 }).then((res) => {
          const obj = res.geoObjects.get(0);
          if (obj) fillAddressFromGeoObject(obj);
        });
        requestQuote(c);
      });
      deliveryMap.geoObjects.add(placemark);
    } else {
      placemark.geometry.setCoordinates(coords);
    }
    deliveryMap.setCenter(coords, Math.max(deliveryMap.getZoom(), 15));
    requestQuote(coords);
  };

  const geocodeAddress = (value) => {
    if (!value) return;
    ymaps.geocode(value, { results: 1, boundedBy: SYK_BOUNDS }).then((res) => {
      const obj = res.geoObjects.get(0);
      if (!obj) { setZoneNote('Адрес не найден. Уточните улицу и дом.', 'error'); return; }
      const coords = obj.geometry.getCoordinates();
      const precision = obj.properties.get('metaDataProperty.GeocoderMetaData.precision');
      fillAddressFromGeoObject(obj);
      setPoint(coords);
      if (precision && precision !== 'exact' && precision !== 'number') {
        setZoneNote('Проверьте номер дома и при необходимости передвиньте точку на карте.', null);
      }
    }).catch(() => setZoneNote('Не удалось определить адрес. Попробуйте ещё раз.', 'error'));
  };

  const buildMap = () => {
    deliveryMap = new ymaps.Map('deliveryMap', {
      center: SYK_CENTER,
      zoom: 12,
      controls: ['zoomControl', 'geolocationControl'],
    });

    const suggest = new ymaps.SuggestView('street', { boundedBy: SYK_BOUNDS, results: 5 });
    suggest.events.add('select', (e) => {
      const value = e.get('item').value;
      const city = (form.city && form.city.value.trim()) || 'Сыктывкар';
      geocodeAddress(value.includes(city) ? value : `${city}, ${value}`);
    });

    // If the user types street+house manually, geocode on house blur too.
    const tryManual = () => {
      const city = (form.city && form.city.value.trim()) || 'Сыктывкар';
      const street = form.street && form.street.value.trim();
      const house = form.house && form.house.value.trim();
      if (street && house) geocodeAddress(`${city}, ${street}, ${house}`);
    };
    if (form.house) form.house.addEventListener('change', tryManual);

    mapAvailable = true;
    setZoneNote('Начните вводить улицу — подскажем адрес и проверим зону доставки.', null);
  };

  const handleMapUnavailable = (msg) => {
    mapAvailable = false;
    setZoneNote(msg, null);
    updateSubmitState();
  };

  const onServiceChange = () => {
    const isDelivery = getServiceType() === 'delivery';
    if (!isDelivery && deliveryCostRow) deliveryCostRow.hidden = true;
    if (isDelivery && deliveryQuote) renderDeliveryQuote(deliveryQuote);
    if (isDelivery && mapAvailable && deliveryMap) {
      try { deliveryMap.container.fitToViewport(); } catch (e) {}
    }
    updateTotals();
    updateSubmitState();
  };

  const initDeliveryMap = () => {
    if (!document.getElementById('deliveryMap')) return;
    if (typeof window.ymaps === 'undefined') {
      handleMapUnavailable('Карта недоступна — заполните адрес вручную, зону проверим при оформлении.');
      return;
    }
    window.ymaps.ready(() => {
      try { buildMap(); } catch (e) {
        handleMapUnavailable('Не удалось загрузить карту — заполните адрес вручную.');
      }
    });
  };

  initDeliveryMap();

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

      window.location.href = result.confirmationUrl;
    } catch (error) {
      submitButton.disabled = false;
      submitButton.textContent = 'Перейти к оплате';
      showMessage(error.message || 'Не удалось создать платёж.', 'error');
    }
  });
});
