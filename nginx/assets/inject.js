(() => {
  "use strict";

  if (window.__libreboxNav) {
    return;
  }

  window.__libreboxNav = true;

  const MOUNT_ID = "librebox-nav";
  const ANCHOR_SELECTOR = '[data-testid="nav-user"]';
  const BUTTON_CLASS = "inline-flex items-center justify-center h-9 w-9 mb-1 rounded-lg cursor-pointer transition-colors text-text-secondary hover:bg-surface-hover hover:text-accent-foreground";
  const NAV_LINKS = [
    {
      label: "Admin",
      url: "/admin/",
      iconSvg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-shield h-5 w-5" aria-hidden="true"><path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/></svg>`,
    },
    {
      label: "Browser",
      url: "/browser/",
      iconSvg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-globe h-5 w-5" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/></svg>`,
    },
    {
      label: "Files",
      url: "/files/",
      iconSvg: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="lucide lucide-folder h-5 w-5" aria-hidden="true"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>`,
    },
  ];

  const buildButton = (navLink) => {
    const button = document.createElement("a");
    button.href = navLink.url;
    button.target = "_blank";
    button.rel = "noopener noreferrer";
    button.title = navLink.label;
    button.setAttribute("aria-label", navLink.label);
    button.className = BUTTON_CLASS;
    button.innerHTML = navLink.iconSvg;
    return button;
  };

  const buildMount = () => {
    const mount = document.createElement("div");
    mount.id = MOUNT_ID;
    mount.style.display = "flex";
    mount.style.flexDirection = "column";
    mount.style.alignItems = "center";
    mount.append(...NAV_LINKS.map(buildButton));
    return mount;
  };

  const insertMount = () => {
    if (document.getElementById(MOUNT_ID)) {
      return;
    }

    const anchor = document.querySelector(ANCHOR_SELECTOR);
    if (!anchor) {
      return;
    }

    const container = anchor.closest(".mt-auto") ?? anchor.parentElement;
    if (!container) {
      return;
    }

    container.insertBefore(buildMount(), container.firstChild);
  };

  let isInsertScheduled = false;
  const scheduleInsert = () => {
    if (isInsertScheduled || document.getElementById(MOUNT_ID)) {
      return;
    }

    isInsertScheduled = true;
    requestAnimationFrame(() => {
      isInsertScheduled = false;
      insertMount();
    });
  };

  const observer = new MutationObserver(scheduleInsert);
  observer.observe(document.body, { childList: true, subtree: true });

  insertMount();
})();