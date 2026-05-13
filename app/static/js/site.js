document.addEventListener('DOMContentLoaded', () => {
  const header = document.querySelector('.site-header');
  const toggle = document.querySelector('.menu-toggle');
  const mobileNav = document.querySelector('.mobile-nav');
  const backdrop = document.querySelector('.mobile-backdrop');
  let revealObserver = null;

  const syncHeaderState = () => {
    if (!header) {
      return;
    }
    header.classList.toggle('has-scrolled', window.scrollY > 18);
  };

  const closeMobileNav = () => {
    if (!toggle || !mobileNav || !backdrop || !header) {
      return;
    }
    toggle.classList.remove('active');
    mobileNav.classList.remove('open');
    backdrop.classList.remove('open');
    header.classList.remove('nav-open');
    document.body.style.overflow = '';
  };

  const openMobileNav = () => {
    if (!toggle || !mobileNav || !backdrop || !header) {
      return;
    }
    toggle.classList.add('active');
    mobileNav.classList.add('open');
    backdrop.classList.add('open');
    header.classList.add('nav-open');
    document.body.style.overflow = 'hidden';
  };

  toggle?.addEventListener('click', () => {
    if (mobileNav?.classList.contains('open')) {
      closeMobileNav();
      return;
    }
    openMobileNav();
  });

  if (mobileNav) {
    const closeBtn = document.createElement('button');
    closeBtn.className = 'mobile-nav-close';
    closeBtn.type = 'button';
    closeBtn.setAttribute('aria-label', 'Закрыть меню');
    closeBtn.textContent = '×';
    closeBtn.addEventListener('click', closeMobileNav);
    mobileNav.insertBefore(closeBtn, mobileNav.firstChild);
  }

  backdrop?.addEventListener('click', closeMobileNav);
  mobileNav?.querySelectorAll('a').forEach(link => link.addEventListener('click', closeMobileNav));
  window.addEventListener('resize', () => {
    if (window.innerWidth > 920) {
      closeMobileNav();
    }
  });
  window.addEventListener('scroll', syncHeaderState, { passive: true });
  syncHeaderState();

  const registerReveal = elements => {
    const list = Array.isArray(elements) || elements instanceof NodeList ? [...elements] : [elements];
    if (!revealObserver) {
      revealObserver = new IntersectionObserver(
        entries => {
          entries.forEach(entry => {
            if (!entry.isIntersecting) {
              return;
            }
            entry.target.classList.add('is-visible');
            revealObserver.unobserve(entry.target);
          });
        },
        { threshold: 0.14, rootMargin: '0px 0px -8% 0px' }
      );
    }

    list.filter(Boolean).forEach(item => {
      if (!item.classList?.contains('reveal')) {
        return;
      }
      revealObserver.observe(item);
    });
  };

  window.registerReveal = registerReveal;

  const revealItems = document.querySelectorAll('.reveal');
  if (revealItems.length) {
    registerReveal(revealItems);
  }

  const dateInput = document.getElementById('res-date');
  const timeInput = document.getElementById('res-time');

  if (dateInput && timeInput) {
    const toLocalDateStr = (d) => {
      const pad = n => String(n).padStart(2, '0');
      return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
    };

    const roundUpTo15 = (d) => {
      const ms = 15 * 60 * 1000;
      return new Date(Math.ceil(d.getTime() / ms) * ms);
    };

    const updateTimeMin = () => {
      const now = new Date();
      const todayStr = toLocalDateStr(now);
      if (dateInput.value === todayStr) {
        const rounded = roundUpTo15(now);
        const pad = n => String(n).padStart(2, '0');
        const minTime = `${pad(rounded.getHours())}:${pad(rounded.getMinutes())}`;
        timeInput.min = minTime > '22:30' ? '23:59' : minTime;
        if (timeInput.value && timeInput.value < timeInput.min) {
          timeInput.value = '';
        }
      } else {
        timeInput.min = '12:00';
      }
    };

    dateInput.min = toLocalDateStr(new Date());
    dateInput.addEventListener('change', updateTimeMin);
    updateTimeMin();
  }

  const reserveForm = document.getElementById('reserve-form');
  if (reserveForm) {
    const submitBtn = reserveForm.querySelector('[data-submit]');
    const msgEl = reserveForm.querySelector('[data-message]');

    const setMessage = (text, isError) => {
      if (!msgEl) return;
      msgEl.textContent = text;
      msgEl.className = 'reserve-message ' + (isError ? 'reserve-message--error' : 'reserve-message--success');
      msgEl.hidden = false;
    };

    reserveForm.addEventListener('submit', async e => {
      e.preventDefault();
      const consent = reserveForm.querySelector('[name="consent"]');
      if (consent && !consent.checked) {
        setMessage('Необходимо согласие на обработку персональных данных.', true);
        return;
      }
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.textContent = 'Отправляем…';
      }
      if (msgEl) msgEl.hidden = true;

      try {
        const resp = await fetch('/reserve', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(Object.fromEntries(new FormData(reserveForm))),
        });
        const data = await resp.json();
        if (data.ok) {
          setMessage('Заявка отправлена! Перезвоним для подтверждения.', false);
          reserveForm.reset();
        } else {
          setMessage(data.error || 'Ошибка. Позвоните нам: +7 (8212) 29-12-47', true);
        }
      } catch {
        setMessage('Ошибка сети. Позвоните нам: +7 (8212) 29-12-47', true);
      } finally {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = 'Отправить заявку';
        }
      }
    });
  }
});
