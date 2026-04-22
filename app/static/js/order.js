document.addEventListener('DOMContentLoaded', () => {
  const list = document.getElementById('orderItemsList');
  const totalEl = document.getElementById('orderTotal');
  const summary = document.getElementById('orderSummary');
  const summaryEmpty = document.getElementById('orderSummaryEmpty');
  const form = document.getElementById('orderForm');
  const submitButton = document.getElementById('submitOrder');
  const phoneInput = document.getElementById('phone');
  const paymentType = document.getElementById('paymentType');
  const changeAmount = document.getElementById('changeAmount');
  const changeAmountLabel = document.getElementById('changeAmountLabel');
  const messageBox = document.getElementById('orderMessage');
  const cart = JSON.parse(localStorage.getItem('cart') || '[]');

  const showMessage = (text, type = 'error') => {
    if (!messageBox) {
      return;
    }

    if (!text) {
      messageBox.hidden = true;
      messageBox.textContent = '';
      messageBox.style.padding = '';
      return;
    }

    const isError = type === 'error';
    messageBox.hidden = false;
    messageBox.textContent = text;
    messageBox.style.color = isError ? '#f2d7d0' : '#e5f4dd';
    messageBox.style.background = isError ? 'rgba(168, 76, 58, 0.18)' : 'rgba(92, 129, 84, 0.18)';
    messageBox.style.border = `1px solid ${isError ? 'rgba(216, 134, 117, 0.32)' : 'rgba(136, 187, 135, 0.32)'}`;
    messageBox.style.borderRadius = '16px';
    messageBox.style.padding = '14px 16px';
  };

  const toggleChangeAmount = () => {
    const visible = paymentType?.value === 'cash';
    if (changeAmountLabel) {
      changeAmountLabel.hidden = !visible;
    }
    if (changeAmount) {
      changeAmount.hidden = !visible;
      if (!visible) {
        changeAmount.value = '';
      }
    }
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
      showMessage('Корзина пуста. Вернитесь в меню и добавьте блюда.', 'error');
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
    submitButton.disabled = false;
  };

  phoneInput?.addEventListener('input', () => {
    phoneInput.value = phoneInput.value.replace(/[^0-9+()\-\s]/g, '').slice(0, 22);
  });

  paymentType?.addEventListener('change', toggleChangeAmount);
  toggleChangeAmount();
  renderSummary();

  form?.addEventListener('submit', async event => {
    event.preventDefault();
    if (!cart.length) {
      showMessage('Корзина пуста.', 'error');
      return;
    }

    showMessage('');
    submitButton.disabled = true;
    submitButton.textContent = 'Отправляем...';

    const payload = {
      customerName: form.customerName.value.trim(),
      phone: form.phone.value.trim(),
      address: {
        city: form.city.value.trim(),
        street: form.street.value.trim(),
        house: form.house.value.trim(),
        apartment: form.apartment.value.trim(),
      },
      paymentType: form.paymentType.value,
      changeAmount: form.changeAmount.value.trim(),
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
      const response = await fetch('/api/orders', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        const details = typeof result.details?.error?.details === 'string'
          ? result.details.error.details
          : typeof result.details?.error?.message === 'string'
            ? result.details.error.message
            : typeof result.details?.raw === 'string'
              ? result.details.raw
              : typeof result.details?.requestError === 'string'
                ? result.details.requestError
                : '';
        throw new Error(details || result.error || 'Не удалось отправить заказ.');
      }

      localStorage.removeItem('cart');
      showMessage('Спасибо. Заказ передан в Marta и уже обрабатывается.', 'success');
      submitButton.textContent = 'Отправлено';
      setTimeout(() => {
        window.location.href = '/menu';
      }, 1300);
    } catch (error) {
      submitButton.disabled = false;
      submitButton.textContent = 'Отправить заказ';
      showMessage(error.message || 'Не удалось отправить заказ.', 'error');
    }
  });
});
