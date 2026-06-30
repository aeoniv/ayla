/**
 * Firestore access layer — the *only* place the service touches state.
 *
 * NOTE ON SCHEMA: the `Entitlement` shape below is a DRAFT placeholder for the
 * skeleton/dry-run. The final entitlement schema is pending review with the
 * project owner before the Stars payment webhook is implemented, so the write
 * path is intentionally left unimplemented (see routes/starsWebhook.ts).
 */

import type { Config } from "./config.js";

/** DRAFT — subject to review before the payment webhook is written. */
export interface Entitlement {
  telegramUserId: number;
  videoId: string;
  grantedAt: FirebaseishTimestamp;
  source: "stars" | "manual";
  telegramPaymentChargeId?: string;
}

/** Minimal timestamp alias so the skeleton compiles without the GCP types. */
type FirebaseishTimestamp = Date;

export interface EntitlementStore {
  /** Returns true when the user is entitled to the given video. */
  hasEntitlement(telegramUserId: number, videoId: string): Promise<boolean>;
  /**
   * Idempotently record a paid entitlement.
   * Intentionally unimplemented until the schema is reviewed.
   */
  grantEntitlement(entitlement: Entitlement): Promise<void>;
}

/**
 * Dry-run / local store. Holds nothing meaningful; lets the skeleton boot and
 * the health/typecheck dry run pass without GCP credentials.
 */
class DryRunStore implements EntitlementStore {
  async hasEntitlement(): Promise<boolean> {
    return false;
  }
  async grantEntitlement(): Promise<void> {
    throw new Error("grantEntitlement not implemented (pending schema review)");
  }
}

/**
 * Firestore-backed store. The read path is a straightforward document lookup;
 * the write path is deferred until the entitlement schema is finalised.
 */
class FirestoreStore implements EntitlementStore {
  private readonly collection = "entitlements";
  // Loaded lazily so the dry run never constructs a GCP client.
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

  private docId(userId: number, videoId: string): string {
    return `${userId}__${videoId}`;
  }

  async hasEntitlement(telegramUserId: number, videoId: string): Promise<boolean> {
    const db = await this.db();
    const snap = await db
      .collection(this.collection)
      .doc(this.docId(telegramUserId, videoId))
      .get();
    return snap.exists;
  }

  async grantEntitlement(_entitlement: Entitlement): Promise<void> {
    // DEFERRED: do not implement until the entitlement schema is reviewed.
    throw new Error("grantEntitlement not implemented (pending schema review)");
  }
}

export function createEntitlementStore(config: Config): EntitlementStore {
  return config.dryRun ? new DryRunStore() : new FirestoreStore(config);
}
