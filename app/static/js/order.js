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
  if (paymentStatus === 'success') {
    localStorage.removeItem('cart');
    showMessage('Оплата прошла. Заказ принят и передаётся на кухню — ждите звонка при необходимости уточнений.', 'success');
    if (submitButton) {
      submitButton.disabled = true;
      submitButton.textContent = 'Заказ оплачен';
    }
  } else if (paymentStatus === 'error') {
    showMessage('Оплата не прошла. Проверьте данные карты и попробуйте снова.', 'error');
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
