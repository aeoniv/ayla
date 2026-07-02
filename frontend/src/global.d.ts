/// <reference types="vite/client" />
// Minimal typings for the Telegram WebApp SDK surface we use.
export {};

interface TelegramWebApp {
  initData: string;
  initDataUnsafe: { user?: { id: number; first_name?: string } };
  ready: () => void;
  expand: () => void;
  openInvoice: (url: string, callback: (status: string) => void) => void;
  openTelegramLink?: (url: string) => void;
  HapticFeedback?: { impactOccurred: (s: string) => void };
}

// requestVideoFrameCallback — the frame-exact video hook used by the authoring
// timeline. Not always present in the TS DOM lib, so we declare the slice we use.
interface VideoFrameCallbackMetadata {
  presentationTime: number;
  expectedDisplayTime: number;
  width: number;
  height: number;
  mediaTime: number;        // presentation timestamp of THIS frame, in seconds
  presentedFrames: number;  // monotonically increasing frame counter
  processingDuration?: number;
}

declare global {
  interface Window {
    Telegram?: { WebApp?: TelegramWebApp };
  }
  interface HTMLVideoElement {
    requestVideoFrameCallback?(
      cb: (now: number, metadata: VideoFrameCallbackMetadata) => void,
    ): number;
    cancelVideoFrameCallback?(handle: number): void;
  }
}
