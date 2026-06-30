/**
 * Parsing of Telegram Stars `successful_payment` updates.
 *
 * Kept free of Express/Firestore so it can be unit-tested in isolation.
 * https://core.telegram.org/bots/api#successfulpayment
 *
 * The bot must create the invoice with an `invoice_payload` that identifies the
 * video. Convention: `vod:<videoId>`.
 */

import type { Entitlement } from "../firestore.js";

interface TelegramUser {
  id: number;
}

interface SuccessfulPayment {
  currency: string;
  total_amount: number;
  invoice_payload: string;
  telegram_payment_charge_id: string;
  provider_payment_charge_id?: string;
}

interface TelegramMessage {
  from?: TelegramUser;
  successful_payment?: SuccessfulPayment;
}

export interface TelegramUpdate {
  update_id?: number;
  message?: TelegramMessage;
}

export const INVOICE_PAYLOAD_PREFIX = "vod:";

export class PaymentParseError extends Error {}

/** Extract the videoId from an `invoice_payload` of the form `vod:<videoId>`. */
export function videoIdFromPayload(payload: string): string {
  if (!payload.startsWith(INVOICE_PAYLOAD_PREFIX)) {
    throw new PaymentParseError("unrecognised invoice_payload");
  }
  const videoId = payload.slice(INVOICE_PAYLOAD_PREFIX.length);
  if (!videoId) throw new PaymentParseError("empty videoId in invoice_payload");
  return videoId;
}

/**
 * Turn a raw Telegram update into an Entitlement to grant, or return null when
 * the update is not a successful payment (which the webhook should ack and
 * ignore, not error on).
 *
 * @throws PaymentParseError when the update *is* a payment but is malformed.
 */
export function entitlementFromUpdate(update: TelegramUpdate): Entitlement | null {
  const payment = update.message?.successful_payment;
  if (!payment) return null;

  const userId = update.message?.from?.id;
  if (typeof userId !== "number") {
    throw new PaymentParseError("missing payer user id");
  }
  if (!payment.telegram_payment_charge_id) {
    throw new PaymentParseError("missing telegram_payment_charge_id");
  }

  const videoId = videoIdFromPayload(payment.invoice_payload);

  return {
    telegramUserId: userId,
    videoId,
    source: "stars",
    telegramPaymentChargeId: payment.telegram_payment_charge_id,
    amount: payment.total_amount,
    currency: payment.currency,
  };
}
