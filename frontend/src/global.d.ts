/// <reference types="vite/client" />
// Minimal typings for the Telegram WebApp SDK surface we use.
export {};

interface TelegramWebApp {
  initData: string;
  initDataUnsafe: { user?: { id: number; first_name?: string } };
  ready: () => void;
  expand: () => void;
  openInvoice: (url: string, callback: (status: string) => void) => void;
  HapticFeedback?: { impactOccurred: (s: string) => void };
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
}
