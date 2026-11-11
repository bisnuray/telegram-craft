// Each test simulates a user journey. The gate lints every captured payload.
import assert from "node:assert/strict";
import { test } from "node:test";
import { buildBot } from "./shop_bot.mjs";
import { GrammyHarness, installLintGate, Recorder } from "../tg_quality/tg_quality.mjs";

const recorder = new Recorder();
installLintGate(recorder);

async function journey(name, body) {
  const bot = new GrammyHarness(buildBot(), recorder);
  await bot.scenario(name, body);
  return bot;
}

test("start", async () => {
  const bot = await journey("start", (b) => b.command("/start"));
  assert.deepEqual(bot.labels, ["Browse catalog", "Settings"]);
});

test("inline navigation and pagination", async () => {
  const bot = await journey("catalog", async (b) => {
    await b.command("/start");
    for (const label of ["Browse catalog", "Next page", "Previous", "Next page", "Next page", "Template 7", "Back", "Back"]) await b.press(label);
  });
  assert.equal(bot.sent("sendMessage").length, 1, "navigation must edit, not stack");
});

test("error messages and stale buttons", async () => {
  const bot = await journey("errors", async (b) => {
    await b.text("hello");
    await b.callback("item:99:0");
    await b.callback("garbage");
  });
  assert.match(bot.sent("sendMessage")[0].text, /Send \/start/);
});

test("unmodified edit is tolerated", async () => {
  await journey("double-tap", async (b) => {
    await b.command("/start");
    await b.press("Settings");
    b.failNext("editMessageText", "Bad Request: message is not modified");
    await b.callback("settings");
  });
});

test("media processing", async () => {
  const bot = await journey("media", async (b) => {
    await b.media("document", { file_name: "a<b>.txt", file_size: 9 });
    await b.media("document", { file_name: "big.bin", file_size: 30_000_000 });
  });
  assert.equal(bot.sent("sendMessage")[0].text, "Converting a&lt;b&gt;.txt…");
  assert.equal(bot.sent("sendDocument").length, 1);
});

test("payment states", async () => {
  const bot = await journey("payment", async (b) => {
    await b.command("/start");
    for (const label of ["Browse catalog", "Template 1", "Buy for 11 Stars"]) await b.press(label);
    await b.preCheckout("order-1", 5);
    await b.preCheckout("order-1", 11);
    await b.successfulPayment("order-1", 11);
  });
  assert.equal(bot.sent("sendInvoice")[0].currency, "XTR");
  assert.deepEqual(bot.sent("answerPreCheckoutQuery").map((a) => a.ok), [false, true]);
});

test("settings and confirmation", async () => {
  await journey("settings", async (b) => {
    await b.command("/start");
    for (const label of ["Settings", "Turn alerts off", "Reset settings", "Keep settings", "Reset settings", "Reset settings now", "Back"]) await b.press(label);
  });
});
