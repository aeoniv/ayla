import { Router, type Request, type Response } from "express";
import { timingSafeEqual } from "node:crypto";
import type { Config } from "../config.js";
import type { EntitlementStore } from "../firestore.js";
import {
  entitlementFromUpdate,
  PaymentParseError,
  type TelegramUpdate,
} from "../payments/stars.js";

/** Constant-time string compare for the webhook secret header. */
function secretMatches(provided: string, expected: string): boolean {
  const a = Buffer.from(provided);
  const b = Buffer.from(expected);
  return a.length === b.length && timingSafeEqual(a, b);
}

/**
 * POST /webhook/stars-payment
 *
 * Handles Telegram Stars `successful_payment` updates:
 *   - authenticates the call via the X-Telegram-Bot-Api-Secret-Token header
 *   - idempotent on telegram_payment_charge_id (via the user+video doc id)
 *   - writes the entitlement to Firestore
 *
 * Returns 200 for anything we have definitively handled (including duplicates
 * and non-payment updates) so Telegram stops retrying; returns 5xx only on
 * transient/internal failure so Telegram retries (safe — the write is
 * idempotent).
 */
export function starsWebhookRouter(
  config: Config,
  store: EntitlementStore,
): Router {
  const router = Router();

  router.post("/stars-payment", async (req: Request, res: Response) => {
    // 1. Authenticate the webhook caller.
    const provided = req.header("x-telegram-bot-api-secret-token") ?? "";
    if (!secretMatches(provided, config.webhookSecret)) {
      res.status(401).json({ ok: false, error: "bad webhook secret" });
      return;
    }

    // 2. Parse the update.
    let entitlement;
    try {
      entitlement = entitlementFromUpdate(req.body as TelegramUpdate);
    } catch (err) {
      if (err instanceof PaymentParseError) {
        // Malformed payment — acking avoids an infinite Telegram retry loop;
        // there is nothing a retry would fix.
        res.status(200).json({ ok: false, error: err.message });
        return;
      }
      throw err;
    }

    // Not a payment update — ack and ignore.
    if (!entitlement) {
      res.status(200).json({ ok: true, ignored: true });
      return;
    }

    // 3. Idempotently record the entitlement.
    try {
      const result = await store.grantEntitlement(entitlement);
      res.status(200).json({
        ok: true,
        created: result.created,
        videoId: entitlement.videoId,
      });
    } catch {
      // Transient/internal — let Telegram retry (grant is idempotent).
      res.status(503).json({ ok: false, error: "could not record entitlement" });
    }
  });

  return router;
}
