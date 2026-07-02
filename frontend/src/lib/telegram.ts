// Thin wrappers over the Telegram WebApp SDK.

export function tg() {
  return window.Telegram?.WebApp;
}

export function initTelegram(): void {
  const w = tg();
  w?.ready();
  w?.expand();
}

export function getInitData(): string {
  // In-app this is the signed initData string the backend validates via HMAC.
  return tg()?.initData ?? "";
}

/** Native Telegram "share to…" sheet for a movement. */
export function shareMovement(name: string): void {
  const w = tg();
  const botUrl = "https://t.me/Ayla_Bot";
  const text = `Learn "${name}" on Ayla — AI-corrected movement coaching`;
  const shareUrl = `https://t.me/share/url?url=${encodeURIComponent(botUrl)}&text=${encodeURIComponent(text)}`;
  if (w?.openTelegramLink) w.openTelegramLink(shareUrl);
  else window.open(shareUrl, "_blank");
}

/** Open a Telegram Stars invoice; resolves with the final status string. */
export function openInvoice(url: string): Promise<string> {
  return new Promise((resolve) => {
    const w = tg();
    if (!w?.openInvoice) {
      // Outside Telegram (dev): open in a new tab so the flow is still testable.
      window.open(url, "_blank");
      resolve("unsupported");
      return;
    }
    w.openInvoice(url, (status) => resolve(status));
  });
}
