import { Router, type Request, type Response } from "express";
import type { Config } from "../config.js";
import { verifyInitData, InitDataError } from "../auth/telegram.js";

/**
 * POST /auth/telegram
 * Body: { "initData": "<raw Telegram.WebApp.initData string>" }
 *
 * Validates the initData HMAC against the bot token and rejects anything else.
 * Implemented as part of the skeleton (auth, not payment/video logic).
 */
export function authRouter(config: Config): Router {
  const router = Router();

  router.post("/telegram", (req: Request, res: Response) => {
    const initData = (req.body?.initData ?? "") as string;
    try {
      const verified = verifyInitData(initData, config.botToken);
      res.json({
        ok: true,
        user: {
          id: verified.user.id,
          username: verified.user.username ?? null,
        },
        authDate: verified.authDate.toISOString(),
      });
    } catch (err) {
      if (err instanceof InitDataError) {
        res.status(401).json({ ok: false, error: err.message });
        return;
      }
      throw err;
    }
  });

  return router;
}
