// Development-only stand-in for window.Telegram.WebApp, for browser previews and
// screenshot tests. Never ship it. A preview that works here is not proof of
// behavior inside a Telegram client.
//
// Load before app code. Choose a state from the query string:
//   ?tgTheme=dark|light  &tgInsetTop=59  &tgInsetBottom=34  &tgContentTop=46  &tgVersion=9.1
(function installTelegramMock() {
  if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.initData) return;
  const q = new URLSearchParams(location.search);
  const scheme = q.get("tgTheme") === "dark" ? "dark" : "light";
  const number = (name) => Number(q.get(name) || 0);

  const themes = {
    light: {
      bg_color: "#ffffff", text_color: "#000000", hint_color: "#707579", link_color: "#3390ec",
      button_color: "#3390ec", button_text_color: "#ffffff", secondary_bg_color: "#f4f4f5",
      header_bg_color: "#ffffff", bottom_bar_bg_color: "#ffffff", accent_text_color: "#3390ec",
      section_bg_color: "#ffffff", section_header_text_color: "#3390ec",
      section_separator_color: "#e7e7e7", subtitle_text_color: "#707579",
      destructive_text_color: "#e53935",
    },
    dark: {
      bg_color: "#212121", text_color: "#ffffff", hint_color: "#aaaaaa", link_color: "#8774e1",
      button_color: "#8774e1", button_text_color: "#ffffff", secondary_bg_color: "#0f0f0f",
      header_bg_color: "#212121", bottom_bar_bg_color: "#212121", accent_text_color: "#8774e1",
      section_bg_color: "#212121", section_header_text_color: "#aaaaaa",
      section_separator_color: "#3d3d3d", subtitle_text_color: "#aaaaaa",
      destructive_text_color: "#ff595a",
    },
  };

  const root = document.documentElement.style;
  const theme = themes[scheme];
  for (const [key, value] of Object.entries(theme)) {
    root.setProperty(`--tg-theme-${key.replaceAll("_", "-")}`, value);
  }
  const safe = { top: number("tgInsetTop"), bottom: number("tgInsetBottom"), left: 0, right: 0 };
  const content = { top: number("tgContentTop"), bottom: 0, left: 0, right: 0 };
  for (const side of ["top", "bottom", "left", "right"]) {
    root.setProperty(`--tg-safe-area-inset-${side}`, `${safe[side]}px`);
    root.setProperty(`--tg-content-safe-area-inset-${side}`, `${content[side]}px`);
  }
  root.setProperty("--tg-viewport-height", `${innerHeight}px`);
  root.setProperty("--tg-viewport-stable-height", `${innerHeight}px`);

  const listeners = {};
  const emit = (event) => (listeners[event] || []).forEach((fn) => fn());

  function makeButton(defaults) {
    const button = {
      ...defaults,
      isVisible: false, isActive: true, isProgressVisible: false,
      setText(text) { button.text = text; render(); return button; },
      setParams(params) { Object.assign(button, params, { isVisible: params.is_visible ?? button.isVisible }); render(); return button; },
      show() { button.isVisible = true; render(); return button; },
      hide() { button.isVisible = false; render(); return button; },
      enable() { button.isActive = true; render(); return button; },
      disable() { button.isActive = false; render(); return button; },
      showProgress() { button.isProgressVisible = true; render(); return button; },
      hideProgress() { button.isProgressVisible = false; render(); return button; },
      onClick(fn) { button.handlers.push(fn); return button; },
      offClick(fn) { button.handlers = button.handlers.filter((h) => h !== fn); return button; },
      handlers: [],
    };
    return button;
  }

  const MainButton = makeButton({ text: "CONTINUE", color: theme.button_color, textColor: theme.button_text_color });
  const SecondaryButton = makeButton({ text: "CANCEL", color: theme.bottom_bar_bg_color, textColor: theme.button_color, position: "left" });
  const BackButton = {
    isVisible: false, handlers: [],
    show() { BackButton.isVisible = true; render(); },
    hide() { BackButton.isVisible = false; render(); },
    onClick(fn) { BackButton.handlers.push(fn); },
    offClick(fn) { BackButton.handlers = BackButton.handlers.filter((h) => h !== fn); },
  };

  // Simulated Telegram chrome, drawn outside the app's own layout.
  let bar, back;
  function render() {
    if (!document.body) return;
    if (!bar) {
      bar = document.createElement("div");
      bar.dataset.tgMock = "bottom-bar";
      bar.style.cssText = "position:fixed;left:0;right:0;bottom:0;display:flex;gap:8px;padding:8px 16px;box-sizing:border-box;z-index:99999";
      document.body.appendChild(bar);
      back = document.createElement("button");
      back.dataset.tgMock = "back";
      back.textContent = "‹ Back";
      back.style.cssText = "position:fixed;top:8px;left:8px;z-index:99999";
      back.onclick = () => BackButton.handlers.forEach((fn) => fn());
      document.body.appendChild(back);
    }
    back.style.display = BackButton.isVisible ? "block" : "none";
    bar.replaceChildren();
    bar.style.background = theme.bottom_bar_bg_color;
    bar.style.paddingBottom = `${8 + safe.bottom}px`;
    for (const b of [SecondaryButton, MainButton]) {
      if (!b.isVisible) continue;
      const el = document.createElement("button");
      el.textContent = b.isProgressVisible ? "…" : b.text;
      el.disabled = !b.isActive;
      el.style.cssText = `flex:1;height:48px;border:0;border-radius:10px;font:600 15px system-ui;background:${b.color};color:${b.textColor}`;
      el.onclick = () => b.handlers.forEach((fn) => fn());
      bar.appendChild(el);
    }
    bar.style.display = MainButton.isVisible || SecondaryButton.isVisible ? "flex" : "none";
  }

  const noop = () => {};
  const version = q.get("tgVersion") || "9.1";
  window.Telegram = {
    WebApp: {
      initData: "mock=1", // deliberately fails server validation
      initDataUnsafe: { user: { id: 1, first_name: "Preview", language_code: "en" } },
      version, platform: "mock", colorScheme: scheme, themeParams: theme,
      isExpanded: true, viewportHeight: innerHeight, viewportStableHeight: innerHeight,
      isActive: true, isFullscreen: false,
      safeAreaInset: safe, contentSafeAreaInset: content,
      MainButton, BottomButton: MainButton, SecondaryButton, BackButton,
      HapticFeedback: { impactOccurred: noop, notificationOccurred: noop, selectionChanged: noop },
      isVersionAtLeast: (v) => {
        const a = version.split(".").map(Number), b = String(v).split(".").map(Number);
        return a[0] > b[0] || (a[0] === b[0] && (a[1] || 0) >= (b[1] || 0));
      },
      ready: noop, expand: noop, close: noop, setHeaderColor: noop, setBackgroundColor: noop,
      setBottomBarColor: noop, enableClosingConfirmation: noop, disableClosingConfirmation: noop,
      disableVerticalSwipes: noop, enableVerticalSwipes: noop, hideKeyboard: noop,
      onEvent(event, fn) { (listeners[event] ||= []).push(fn); },
      offEvent(event, fn) { listeners[event] = (listeners[event] || []).filter((h) => h !== fn); },
      showAlert(message, cb) { alert(message); cb && cb(); },
      showConfirm(message, cb) { cb && cb(confirm(message)); },
      showPopup(params, cb) { alert(params.message); cb && cb("ok"); },
      openLink: (url) => window.open(url, "_blank"), openTelegramLink: noop,
      __mock: { emit },
    },
  };
  document.addEventListener("DOMContentLoaded", render);
})();
