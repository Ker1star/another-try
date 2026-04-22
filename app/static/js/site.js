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
});
