function waitForElement(selector, timeoutMs = 10000) {
  const found = document.querySelector(selector);
  if (found) return Promise.resolve(found);
  return new Promise((resolve) => {
    const timeout = globalThis.setTimeout(() => {
      observer.disconnect();
      resolve(document.querySelector(selector));
    }, timeoutMs);
    const observer = new MutationObserver(() => {
      const element = document.querySelector(selector);
      if (!element) return;
      globalThis.clearTimeout(timeout);
      observer.disconnect();
      resolve(element);
    });
    observer.observe(document.body, { childList: true, subtree: true });
  });
}

export default async function registerJevRouterSurface(surfaces) {
  surfaces.registerSurface({
    id: 'jev_router',
    title: 'Jev Router',
    icon: 'route',
    order: 45,
    modalPath: '/plugins/jev_router/webui/jev-router-panel.html',
    async open() {
      await waitForElement('[data-surface-id="jev_router"] .jev-panel');
      window.__jevRouterPanel?.refresh?.();
    },
    async close() {},
  });
}
