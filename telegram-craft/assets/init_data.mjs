// Validate Telegram Mini App init data on a Node.js server (no dependencies).
// Copy into the backend. Pass the raw `Telegram.WebApp.initData` string, never
// `initDataUnsafe`. Spec: https://core.telegram.org/bots/webapps
import { createHmac, timingSafeEqual } from "node:crypto";

export class InitDataError extends Error {}

/**
 * Return `{ authDate, user, fields }`, or throw InitDataError.
 *
 * The HMAC data-check-string covers every received field except `hash`, so a
 * `signature` field stays in it. Pick `maxAgeSeconds` per endpoint.
 *
 * @param {string} initData
 * @param {string} botToken
 * @param {{maxAgeSeconds?: number, now?: number, futureSkewSeconds?: number}} [options]
 */
export function validateInitData(initData, botToken, options = {}) {
  const { maxAgeSeconds = 3600, now = Date.now() / 1000, futureSkewSeconds = 60 } = options;

  const params = new URLSearchParams(initData);
  const fields = {};
  for (const [key, value] of params) {
    if (Object.hasOwn(fields, key)) throw new InitDataError("init data contains duplicate keys");
    fields[key] = value;
  }

  const receivedHash = fields.hash;
  if (!receivedHash) throw new InitDataError("init data has no hash");
  delete fields.hash;

  const checkString = Object.keys(fields)
    .sort()
    .map((key) => `${key}=${fields[key]}`)
    .join("\n");

  const secret = createHmac("sha256", "WebAppData").update(botToken).digest();
  const expected = createHmac("sha256", secret).update(checkString).digest();
  const received = Buffer.from(receivedHash, "hex");
  if (received.length !== expected.length || !timingSafeEqual(received, expected)) {
    throw new InitDataError("init data signature mismatch");
  }

  const authDate = Number.parseInt(fields.auth_date ?? "", 10);
  if (!Number.isFinite(authDate)) throw new InitDataError("init data has no usable auth_date");
  if (authDate > now + futureSkewSeconds) throw new InitDataError("init data is from the future");
  if (now - authDate > maxAgeSeconds) throw new InitDataError("init data has expired");

  let user = null;
  if (fields.user !== undefined) {
    try {
      user = JSON.parse(fields.user);
    } catch {
      throw new InitDataError("init data user is not valid JSON");
    }
    if (typeof user !== "object" || user === null || user.id === undefined) {
      throw new InitDataError("init data user has no id");
    }
  }

  return { authDate, user, fields };
}
