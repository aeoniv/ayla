/**
 * Telegram WebApp initData validation.
 *
 * This is *not* payment or video logic — it is the authentication primitive the
 * whole service depends on, so it is implemented (and tested) as part of the
 * skeleton. See:
 * https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
 *
 * Algorithm (HMAC-SHA256):
 *   secret_key = HMAC_SHA256(key="WebAppData", message=bot_token)
 *   hash       = HMAC_SHA256(key=secret_key, message=data_check_string)
 * where data_check_string is every initData field except `hash`, sorted by key
 * and joined by "\n" as "key=value".
 */

import { createHmac, timingSafeEqual } from "node:crypto";

export interface TelegramUser {
  id: number;
  first_name?: string;
  last_name?: string;
  username?: string;
  language_code?: string;
  is_premium?: boolean;
}

export interface VerifiedInitData {
  user: TelegramUser;
  authDate: Date;
  raw: URLSearchParams;
}

export class InitDataError extends Error {}

/**
 * Validate a raw `initData` query string against the bot token.
 *
 * @param initData  The raw `window.Telegram.WebApp.initData` string.
 * @param botToken  The bot token (secret).
 * @param maxAgeSeconds  Reject data older than this (default 1h). 0 disables.
 * @throws InitDataError when the signature is missing, malformed, or invalid.
 */
export function verifyInitData(
  initData: string,
  botToken: string,
  maxAgeSeconds = 3600,
): VerifiedInitData {
  if (!initData) throw new InitDataError("empty initData");

  const params = new URLSearchParams(initData);
  const providedHash = params.get("hash");
  if (!providedHash) throw new InitDataError("missing hash");

  // Build the data_check_string: all fields except `hash`, sorted, "k=v"\n-joined.
  const pairs: string[] = [];
  for (const [key, value] of params.entries()) {
    if (key === "hash") continue;
    pairs.push(`${key}=${value}`);
  }
  pairs.sort();
  const dataCheckString = pairs.join("\n");

  const secretKey = createHmac("sha256", "WebAppData").update(botToken).digest();
  const computedHash = createHmac("sha256", secretKey)
    .update(dataCheckString)
    .digest("hex");

  // Constant-time comparison to avoid leaking via timing.
  const a = Buffer.from(computedHash, "hex");
  const b = Buffer.from(providedHash, "hex");
  if (a.length !== b.length || !timingSafeEqual(a, b)) {
    throw new InitDataError("signature mismatch");
  }

  // Optional freshness check on auth_date (unix seconds).
  const authDateRaw = params.get("auth_date");
  if (!authDateRaw) throw new InitDataError("missing auth_date");
  const authDate = new Date(Number(authDateRaw) * 1000);
  if (maxAgeSeconds > 0) {
    const ageSeconds = (Date.now() - authDate.getTime()) / 1000;
    if (ageSeconds > maxAgeSeconds) throw new InitDataError("initData expired");
  }

  const userRaw = params.get("user");
  if (!userRaw) throw new InitDataError("missing user");
  let user: TelegramUser;
  try {
    user = JSON.parse(userRaw) as TelegramUser;
  } catch {
    throw new InitDataError("malformed user payload");
  }
  if (typeof user.id !== "number") throw new InitDataError("missing user.id");

  return { user, authDate, raw: params };
}
