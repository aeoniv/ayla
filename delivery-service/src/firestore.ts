/**
 * Firestore access layer — the *only* place the service touches state.
 *
 * Entitlement schema (reviewed & approved):
 *   collection: "entitlements"
 *   doc id:     `${telegramUserId}__${videoId}`   (one doc per user+video)
 *   fields:     telegramUserId, videoId, source, telegramPaymentChargeId,
 *               amount, currency, grantedAt (server timestamp)
 *
 * Entitlements are permanent (no expiry). Idempotency is achieved by the doc id:
 * a webhook retry or a repeat purchase of the same video resolves to the same
 * document and is a no-op.
 */

import type { Config } from "./config.js";

export interface Entitlement {
  telegramUserId: number;
  videoId: string;
  source: "stars" | "manual";
  /** Telegram's idempotency key for the payment. */
  telegramPaymentChargeId: string;
  /** Stars amount (XTR is an integer currency, no minor units). */
  amount: number;
  /** ISO-4217-ish currency code; Telegram Stars is "XTR". */
  currency: string;
}

/** Result of an idempotent grant: created=false means it already existed. */
export interface GrantResult {
  created: boolean;
}

export interface EntitlementStore {
  /** Returns true when the user is entitled to the given video. */
  hasEntitlement(telegramUserId: number, videoId: string): Promise<boolean>;
  /** Idempotently record a paid entitlement (no-op if already present). */
  grantEntitlement(entitlement: Entitlement): Promise<GrantResult>;
}

function docId(userId: number, videoId: string): string {
  return `${userId}__${videoId}`;
}

/**
 * In-memory store for local/dry-run mode and unit tests. Boots without GCP
 * credentials and preserves the idempotency contract so the webhook can be
 * exercised offline.
 */
export class InMemoryStore implements EntitlementStore {
  private readonly docs = new Map<string, Entitlement>();

  async hasEntitlement(telegramUserId: number, videoId: string): Promise<boolean> {
    return this.docs.has(docId(telegramUserId, videoId));
  }

  async grantEntitlement(entitlement: Entitlement): Promise<GrantResult> {
    const id = docId(entitlement.telegramUserId, entitlement.videoId);
    if (this.docs.has(id)) return { created: false };
    this.docs.set(id, entitlement);
    return { created: true };
  }
}

/**
 * Firestore-backed store. Writes go through a transaction so the existence
 * check and the create are atomic (idempotent under concurrent webhook
 * retries).
 */
class FirestoreStore implements EntitlementStore {
  private readonly collection = "entitlements";
  private dbPromise?: Promise<import("@google-cloud/firestore").Firestore>;

  constructor(private readonly config: Config) {}

  private async db() {
    if (!this.dbPromise) {
      this.dbPromise = import("@google-cloud/firestore").then(
        ({ Firestore }) => new Firestore({ projectId: this.config.projectId }),
      );
    }
    return this.dbPromise;
  }

  async hasEntitlement(telegramUserId: number, videoId: string): Promise<boolean> {
    const db = await this.db();
    const snap = await db
      .collection(this.collection)
      .doc(docId(telegramUserId, videoId))
      .get();
    return snap.exists;
  }

  async grantEntitlement(entitlement: Entitlement): Promise<GrantResult> {
    const db = await this.db();
    const { FieldValue } = await import("@google-cloud/firestore");
    const ref = db
      .collection(this.collection)
      .doc(docId(entitlement.telegramUserId, entitlement.videoId));

    return db.runTransaction(async (tx) => {
      const snap = await tx.get(ref);
      if (snap.exists) return { created: false };
      tx.create(ref, {
        telegramUserId: entitlement.telegramUserId,
        videoId: entitlement.videoId,
        source: entitlement.source,
        telegramPaymentChargeId: entitlement.telegramPaymentChargeId,
        amount: entitlement.amount,
        currency: entitlement.currency,
        grantedAt: FieldValue.serverTimestamp(),
      });
      return { created: true };
    });
  }
}

export function createEntitlementStore(config: Config): EntitlementStore {
  return config.dryRun ? new InMemoryStore() : new FirestoreStore(config);
}
