import { Router, type Request, type Response } from "express";
import type { Config } from "../config.js";
import type { EntitlementStore } from "../firestore.js";

/**
 * POST /webhook/stars-payment
 *
 * Handles Telegram Stars `successful_payment` updates. Must be:
 *   - idempotent on `telegram_payment_charge_id`
 *   - write the entitlement to Firestore
 *
 * ┌──────────────────────────────────────────────────────────────────────┐
 * │ DELIBERATELY NOT IMPLEMENTED.                                          │
 * │ The owner wants to review the entitlement schema before this logic is  │
 * │ written. Do not implement the payment/entitlement-write path here      │
 * │ until that review is complete. See firestore.ts (Entitlement = DRAFT). │
 * └──────────────────────────────────────────────────────────────────────┘
 */
export function starsWebhookRouter(
  _config: Config,
  _store: EntitlementStore,
): Router {
  const router = Router();

  router.post("/stars-payment", (_req: Request, res: Response) => {
    res.status(501).json({
      ok: false,
      error: "stars-payment webhook not implemented (pending schema review)",
    });
  });

  return router;
}
