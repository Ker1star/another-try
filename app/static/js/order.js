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
  const pickupHint = document.getElementById('pickupHint');
  const serviceInputs = form ? Array.from(form.querySelectorAll('input[name="serviceType"]')) : [];
  const cart = JSON.parse(localStorage.getItem('cart') || '[]');

  const getServiceType = () => {
    const checked = serviceInputs.find((input) => input.checked);
    return checked ? checked.value : 'delivery';
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
        if (pickupHint) {
          pickupHint.textContent = `Готовим минимум ${data.leadMinutes} минут. Заберите до ${data.closesAt}.`;
        }
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

    totalEl.textContent = `${total.toFixed(0)} ₽`;
    submitButton.disabled = consentCheck ? !consentCheck.checked : false;
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

  consentCheck?.addEventListener('change', () => {
    if (cart.length && consentCheck.checked) {
      submitButton.disabled = false;
    } else {
      submitButton.disabled = true;
    }
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
