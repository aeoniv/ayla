import { test } from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import { verifyInitData, InitDataError } from "../src/auth/telegram.js";

const BOT_TOKEN = "123456:TEST-bot-token";

/** Build a correctly-signed initData string for the given fields. */
function signInitData(
  fields: Record<string, string>,
  botToken = BOT_TOKEN,
): string {
  const pairs = Object.entries(fields).map(([k, v]) => `${k}=${v}`);
  pairs.sort();
  const dataCheckString = pairs.join("\n");
  const secretKey = createHmac("sha256", "WebAppData").update(botToken).digest();
  const hash = createHmac("sha256", secretKey).update(dataCheckString).digest("hex");
  const params = new URLSearchParams(fields);
  params.set("hash", hash);
  return params.toString();
}

test("accepts valid, fresh initData", () => {
  const initData = signInitData({
    auth_date: String(Math.floor(Date.now() / 1000)),
    query_id: "AAH",
    user: JSON.stringify({ id: 42, username: "ayla" }),
  });
  const verified = verifyInitData(initData, BOT_TOKEN);
  assert.equal(verified.user.id, 42);
  assert.equal(verified.user.username, "ayla");
});

test("rejects a tampered hash", () => {
  const initData = signInitData({
    auth_date: String(Math.floor(Date.now() / 1000)),
    user: JSON.stringify({ id: 7 }),
  }).replace(/hash=[0-9a-f]+/, "hash=deadbeef");
  assert.throws(() => verifyInitData(initData, BOT_TOKEN), InitDataError);
});

test("rejects initData signed with the wrong token", () => {
  const initData = signInitData(
    {
      auth_date: String(Math.floor(Date.now() / 1000)),
      user: JSON.stringify({ id: 7 }),
    },
    "999999:WRONG-token",
  );
  assert.throws(() => verifyInitData(initData, BOT_TOKEN), InitDataError);
});

test("rejects expired initData", () => {
  const initData = signInitData({
    auth_date: String(Math.floor(Date.now() / 1000) - 7200),
    user: JSON.stringify({ id: 7 }),
  });
  assert.throws(
    () => verifyInitData(initData, BOT_TOKEN, 3600),
    /expired/,
  );
});

test("rejects missing hash", () => {
  assert.throws(() => verifyInitData("auth_date=1&user=%7B%7D", BOT_TOKEN), InitDataError);
});
