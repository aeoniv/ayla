import { Router, type Request, type Response } from "express";
import type { Config } from "../config.js";
import type { EntitlementStore } from "../firestore.js";
import type { ManifestSigner } from "../storage.js";
import { verifyInitData, InitDataError } from "../auth/telegram.js";

/**
 * GET /manifest/:videoId
 * Auth: initData passed via the `Authorization: tma <initData>` header.
 *
 * Flow (skeleton): authenticate -> check Firestore entitlement -> return a
 * 10-minute V4 signed URL for the HLS manifest.
 *
 * The signed-URL minting itself is DEFERRED video logic (see storage.ts); this
 * route wires the flow and returns 501 until that logic is enabled.
 */
export function manifestRouter(
  config: Config,
  store: EntitlementStore,
  signer: ManifestSigner,
): Router {
  const router = Router();

  router.get("/:videoId", async (req: Request, res: Response) => {
    const videoId = req.params.videoId;
    if (!videoId) {
      res.status(400).json({ ok: false, error: "missing videoId" });
      return;
    }

    // Authenticate via initData in the Authorization header ("tma <initData>").
    const authHeader = req.header("authorization") ?? "";
    const initData = authHeader.replace(/^tma\s+/i, "");
    let userId: number;
    try {
      userId = verifyInitData(initData, config.botToken).user.id;
    } catch (err) {
      if (err instanceof InitDataError) {
        res.status(401).json({ ok: false, error: err.message });
        return;
      }
      throw err;
    }

    const entitled = await store.hasEntitlement(userId, videoId);
    if (!entitled) {
      res.status(403).json({ ok: false, error: "no entitlement" });
      return;
    }

    // DEFERRED: enable once video logic is implemented and dry run passes.
    try {
      const url = await signer.signManifestUrl(videoId);
      res.json({ ok: true, url, expiresInSeconds: config.signedUrlTtlSeconds });
    } catch {
      res
        .status(501)
        .json({ ok: false, error: "signed-url generation not yet implemented" });
    }
  });

  return router;
}
