document.addEventListener('DOMContentLoaded', async () => {
  const container = document.getElementById('menuContainer');
  const tabsList = document.getElementById('catTabs');
  if (!container || !tabsList) {
    return;
  }

  const categoryOrder = ['Закуски', 'Салаты', 'Супы', 'Пицца', 'Паста', 'Горячие блюда', 'Десерты'];
  const fallbackDescription = 'Описание появится после следующего обновления меню.';
  const usedSlugs = new Map();
  const slugify = value => {
    const base = String(value || 'category')
      .trim()
      .toLowerCase()
      .normalize('NFKC')
      .replace(/[^\p{Letter}\p{Number}]+/gu, '-')
      .replace(/^-+|-+$/g, '') || 'category';
    const count = usedSlugs.get(base) || 0;
    usedSlugs.set(base, count + 1);
    return count ? `${base}-${count + 1}` : base;
  };
  const interactiveMode = Boolean(window.MENU_INTERACTIVE);
  const menuMode = window.MENU_MODE || 'restaurant';

  try {
    const response = await fetch(MENU_API_URL);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const { data: items } = await response.json();
    const categories = items.filter(item => item.isParent && item.hierarchicalParent === null);
    const dishes = items.filter(item => !item.isParent);

    categories.sort((left, right) => {
      const leftIndex = categoryOrder.findIndex(name => left.name.toLowerCase().includes(name.toLowerCase()));
      const rightIndex = categoryOrder.findIndex(name => right.name.toLowerCase().includes(name.toLowerCase()));
      if (leftIndex === -1 && rightIndex === -1) {
        return left.name.localeCompare(right.name);
      }
      if (leftIndex === -1) {
        return 1;
      }
      if (rightIndex === -1) {
        return -1;
      }
      return leftIndex - rightIndex;
    });

    if (!categories.length) {
      container.innerHTML = `<div class="menu-empty">${menuMode === 'delivery' ? 'Сейчас в меню доставки нет доступных категорий.' : 'Сейчас в меню ресторана нет опубликованных категорий.'}</div>`;
      if (interactiveMode) {
        initCart();
      }
      return;
    }

    categories.forEach((category, index) => {
      const tabItem = document.createElement('li');
      const tab = document.createElement('a');
      tab.className = 'category-tab';
      tab.href = `#${slugify(category.name)}`;
      tab.textContent = category.name;
      if (index === 0) {
        tab.classList.add('active');
      }
      tabItem.appendChild(tab);
      tabsList.appendChild(tabItem);
    });

    const observedSections = [];

    categories.forEach((category, index) => {
      const section = document.createElement('section');
      section.className = `menu-section reveal${index ? ' delay-1' : ''}`;

      const sectionId = slugify(category.name);
      const heading = document.createElement('h2');
      heading.className = 'menu-category';
      heading.id = sectionId;
      heading.textContent = category.name;

      const sectionHead = document.createElement('div');
      sectionHead.className = 'menu-section-head';
      sectionHead.appendChild(heading);

      const description = document.createElement('p');
      description.textContent = menuMode === 'delivery'
        ? `Позиции категории «${category.name.toLowerCase()}», доступные для доставки и самовывоза.`
        : `Позиции категории «${category.name.toLowerCase()}», доступные в основном меню ресторана.`;
      sectionHead.appendChild(description);

      const grid = document.createElement('div');
      grid.className = 'menu-grid';

      const categoryDishes = dishes.filter(dish => dish.hierarchicalParent === category.hierarchicalId);
      if (!categoryDishes.length) {
        const empty = document.createElement('div');
        empty.className = 'menu-empty';
        empty.textContent = 'В этой категории сейчас нет доступных позиций.';
        grid.appendChild(empty);
      }

      categoryDishes.forEach(dish => {
        const card = document.createElement('article');
        card.className = 'menu-item';

        const media = document.createElement('div');
        media.className = 'menu-item-media';

        const image = document.createElement('img');
        image.src = dish.images?.length ? dish.images[0] : '/static/images/logo-heart.jpg';
        image.alt = dish.name;
        image.loading = 'lazy';
        media.appendChild(image);

        const info = document.createElement('div');
        info.className = 'info';

        const title = document.createElement('h3');
        title.textContent = dish.name;
        info.appendChild(title);

        const copy = document.createElement('p');
        copy.className = 'description';
        copy.textContent = dish.description_simple?.trim() || fallbackDescription;
        info.appendChild(copy);

        const meta = document.createElement('div');
        meta.className = 'menu-meta';

        const price = document.createElement('span');
        price.className = 'price';
        const numericPrice = Number(dish.price);
        price.textContent = `${Number.isFinite(numericPrice) ? numericPrice.toFixed(0) : '0'} ₽`;
        meta.appendChild(price);
        info.appendChild(meta);

        if (interactiveMode) {
          const action = document.createElement('button');
          action.type = 'button';
          action.className = 'button btn-add';
          action.textContent = 'Добавить в корзину';
          action.addEventListener('click', () => addToCart(dish));
          info.appendChild(action);
        } else {
          const action = document.createElement('a');
          action.className = dish.availableForDelivery ? 'button-secondary' : 'button-ghost';
          action.href = dish.availableForDelivery ? `${window.DELIVERY_PAGE_URL}#${sectionId}` : '#';
          action.textContent = dish.availableForDelivery ? 'Есть в доставке' : 'Только в ресторане';
          if (!dish.availableForDelivery) {
            action.setAttribute('aria-disabled', 'true');
            action.addEventListener('click', event => event.preventDefault());
          }
          info.appendChild(action);
        }

        card.append(media, info);
        grid.appendChild(card);
      });

      section.append(sectionHead, grid);
      container.appendChild(section);
      window.registerReveal?.(section);
      observedSections.push(heading);
    });

    const navOffset = 128;
    tabsList.querySelectorAll('.category-tab').forEach(tab => {
      tab.addEventListener('click', event => {
        event.preventDefault();
        const target = document.getElementById(tab.hash.slice(1));
        if (!target) {
          return;
        }
        window.scrollTo({
          top: target.getBoundingClientRect().top + window.pageYOffset - navOffset,
          behavior: 'smooth'
        });
      });
    });

    const tabsObserver = new IntersectionObserver(
      entries => {
        entries.forEach(entry => {
          const targetLink = tabsList.querySelector(`.category-tab[href="#${entry.target.id}"]`);
          if (!targetLink || !entry.isIntersecting) {
            return;
          }
          tabsList.querySelectorAll('.category-tab').forEach(link => link.classList.remove('active'));
          targetLink.classList.add('active');
        });
      },
      { rootMargin: '-40% 0px -48% 0px', threshold: 0.01 }
    );
    observedSections.forEach(section => tabsObserver.observe(section));

    if (window.location.hash) {
      const hashTarget = document.getElementById(decodeURIComponent(window.location.hash.slice(1)));
      if (hashTarget) {
        requestAnimationFrame(() => {
          window.scrollTo({
            top: hashTarget.getBoundingClientRect().top + window.pageYOffset - navOffset,
            behavior: 'smooth'
          });
        });
      }
    }

    if (interactiveMode) {
      initCart();
    }
  } catch (error) {
    console.error('Ошибка при загрузке меню:', error);
    container.innerHTML = `<div class="menu-empty">${menuMode === 'delivery' ? 'Не удалось загрузить меню доставки. Попробуйте обновить страницу чуть позже.' : 'Не удалось загрузить меню ресторана. Попробуйте обновить страницу чуть позже.'}</div>`;
    if (interactiveMode) {
      initCart();
    }
  }
});

function initCart() {
  const overlay = document.getElementById('cartOverlay');
  const sidebar = document.getElementById('cartSidebar');
  const openButton = document.getElementById('cartBtn');
  const openMobileButton = document.getElementById('cartBtnMobile');
  const closeButton = document.getElementById('closeCart');
  const list = document.getElementById('cartList');
  const total = document.getElementById('cartTotal');
  const checkout = document.getElementById('checkoutBtn');
  const countBadge = document.getElementById('cartCount');

  if (!list || !total || !checkout || !countBadge) {
    return;
  }

  const state = JSON.parse(localStorage.getItem('cart') || '[]');

  const openCart = () => {
    overlay?.classList.add('open');
    sidebar?.classList.add('open');
    document.body.style.overflow = 'hidden';
  };

  const closeCart = () => {
    overlay?.classList.remove('open');
    sidebar?.classList.remove('open');
    document.body.style.overflow = '';
  };

  const render = () => {
    list.innerHTML = '';
    let amount = 0;

    if (!state.length) {
      const empty = document.createElement('li');
      empty.className = 'menu-empty';
      empty.textContent = 'Добавьте блюда в корзину, чтобы перейти к оформлению.';
      list.appendChild(empty);
    }

    state.forEach((item, index) => {
      const row = document.createElement('li');
      row.className = 'cart-row';

      const copy = document.createElement('div');
      copy.className = 'cart-copy';

      const name = document.createElement('span');
      name.className = 'cart-name';
      name.textContent = item.name;
      copy.appendChild(name);

      const controls = document.createElement('div');
      controls.className = 'cart-controls';

      const minus = document.createElement('button');
      minus.type = 'button';
      minus.className = 'cart-qty';
      minus.textContent = '−';
      minus.addEventListener('click', () => {
        item.qty = Math.max(1, (item.qty || 1) - 1);
        persist();
      });

      const qty = document.createElement('span');
      qty.className = 'cart-qty-value';
      qty.textContent = String(item.qty || 1);

      const plus = document.createElement('button');
      plus.type = 'button';
      plus.className = 'cart-qty';
      plus.textContent = '+';
      plus.addEventListener('click', () => {
        item.qty = (item.qty || 1) + 1;
        persist();
      });

      controls.append(minus, qty, plus);

      const actions = document.createElement('div');
      actions.className = 'cart-actions';

      const price = document.createElement('span');
      price.className = 'cart-price';
      const lineAmount = (Number(item.price) || 0) * (item.qty || 1);
      price.textContent = `${lineAmount.toFixed(0)} ₽`;
      amount += lineAmount;

      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'cart-remove';
      remove.textContent = '×';
      remove.setAttribute('aria-label', `Удалить ${item.name}`);
      remove.addEventListener('click', () => {
        state.splice(index, 1);
        persist();
      });

      actions.append(price, remove);
      row.append(copy, controls, actions);
      list.appendChild(row);
    });

    total.textContent = `${amount.toFixed(0)} ₽`;
    countBadge.textContent = String(state.reduce((sum, item) => sum + (item.qty || 1), 0));
    checkout.disabled = state.length === 0;
  };

  const persist = () => {
    localStorage.setItem('cart', JSON.stringify(state));
    render();
  };

  window.addToCart = dish => {
    const existing = state.find(item => item.id === dish.id);
    if (existing) {
      existing.qty = (existing.qty || 1) + 1;
    } else {
      state.push({
        id: dish.id,
        hierarchicalId: dish.hierarchicalId,
        prestoId: dish.prestoId ?? null,
        externalId: dish.externalId ?? null,
        nomNumber: dish.nomNumber ?? null,
        name: dish.name,
        price: Number(dish.price) || 0,
        qty: 1,
        image: dish.images?.[0] || null
      });
    }

    persist();
    openCart();
  };

  openButton?.addEventListener('click', openCart);
  openMobileButton?.addEventListener('click', openCart);
  closeButton?.addEventListener('click', closeCart);
  overlay?.addEventListener('click', closeCart);

  checkout.addEventListener('click', () => {
    window.location.href = window.ORDER_PAGE_URL || '/order';
  });

  render();
}
