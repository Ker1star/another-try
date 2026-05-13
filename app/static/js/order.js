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
  const cart = JSON.parse(localStorage.getItem('cart') || '[]');

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

    const payload = {
      customerName: form.customerName.value.trim(),
      phone: form.phone.value.trim(),
      email: form.email.value.trim(),
      address: {
        city: form.city.value.trim(),
        street: form.street.value.trim(),
        house: form.house.value.trim(),
        apartment: form.apartment.value.trim(),
      },
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
