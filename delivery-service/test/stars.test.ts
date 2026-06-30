import { test } from "node:test";
import assert from "node:assert/strict";
import {
  entitlementFromUpdate,
  videoIdFromPayload,
  PaymentParseError,
  type TelegramUpdate,
} from "../src/payments/stars.js";
import { InMemoryStore } from "../src/firestore.js";

function paymentUpdate(overrides: Record<string, unknown> = {}): TelegramUpdate {
  return {
    update_id: 1,
    message: {
      from: { id: 555 },
      successful_payment: {
        currency: "XTR",
        total_amount: 100,
        invoice_payload: "vod:movie-42",
        telegram_payment_charge_id: "charge_abc",
        ...overrides,
      },
    },
  };
}

test("videoIdFromPayload extracts the id", () => {
  assert.equal(videoIdFromPayload("vod:movie-42"), "movie-42");
});

test("videoIdFromPayload rejects bad payloads", () => {
  assert.throws(() => videoIdFromPayload("movie-42"), PaymentParseError);
  assert.throws(() => videoIdFromPayload("vod:"), PaymentParseError);
});

test("entitlementFromUpdate maps a successful payment", () => {
  const e = entitlementFromUpdate(paymentUpdate());
  assert.deepEqual(e, {
    telegramUserId: 555,
    videoId: "movie-42",
    source: "stars",
    telegramPaymentChargeId: "charge_abc",
    amount: 100,
    currency: "XTR",
  });
});

test("entitlementFromUpdate returns null for non-payment updates", () => {
  assert.equal(entitlementFromUpdate({ update_id: 2, message: {} }), null);
});

test("entitlementFromUpdate throws on a payment missing the charge id", () => {
  assert.throws(
    () => entitlementFromUpdate(paymentUpdate({ telegram_payment_charge_id: "" })),
    PaymentParseError,
  );
});

test("grantEntitlement is idempotent on repeat delivery", async () => {
  const store = new InMemoryStore();
  const e = entitlementFromUpdate(paymentUpdate())!;

  const first = await store.grantEntitlement(e);
  const second = await store.grantEntitlement(e);

  assert.equal(first.created, true);
  assert.equal(second.created, false);
  assert.equal(await store.hasEntitlement(555, "movie-42"), true);
});
