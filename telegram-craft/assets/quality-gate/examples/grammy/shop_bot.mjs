// Example bot used to demonstrate the quality gate (grammY).
import { Bot, GrammyError, InlineKeyboard, InputFile } from "grammy";

const ITEMS = new Map(Array.from({ length: 7 }, (_, i) => [i + 1, [`Template ${i + 1}`, 11 + i]]));
const PAGE_SIZE = 3;
const MAX_DOWNLOAD = 20_000_000;
const HTML = { parse_mode: "HTML" };
const escapeHtml = (s) => s.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");

const home = () => ["<b>Template store</b>\nBuy document templates and manage alerts.",
  new InlineKeyboard().text("Browse catalog", "cat:0").row().text("Settings", "settings")];

function catalog(requested) {
  const ids = [...ITEMS.keys()];
  const pages = Math.floor((ids.length - 1) / PAGE_SIZE);
  const page = Math.max(0, Math.min(requested, pages));
  const kb = new InlineKeyboard();
  for (const id of ids.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE)) kb.text(ITEMS.get(id)[0], `item:${id}:${page}`).row();
  if (page) kb.text("Previous", `cat:${page - 1}`);
  if (page < pages) kb.text("Next page", `cat:${page + 1}`);
  return [`<b>Catalog</b>\nPage ${page + 1} of ${pages + 1}`, kb.row().text("Back", "home")];
}

const settingsView = (alerts) => [`<b>Settings</b>\nAlerts: ${alerts ? "On" : "Off"}`,
  new InlineKeyboard().text(`Turn alerts ${alerts ? "off" : "on"}`, "alerts").row().text("Reset settings", "reset:ask").row().text("Back", "home")];

async function show(ctx, [text, reply_markup]) {
  try {
    await ctx.editMessageText(text, { ...HTML, reply_markup });
  } catch (error) {
    if (!(error instanceof GrammyError && error.description.includes("message is not modified"))) throw error;
  }
}

export function buildBot() {
  const bot = new Bot("123456:TEST-TOKEN");
  const alerts = new Map();
  const alertsOf = (ctx) => alerts.get(ctx.from.id) ?? true;

  bot.command("start", async (ctx) => {
    const [text, reply_markup] = home();
    await ctx.reply(text, { ...HTML, reply_markup });
  });
  bot.callbackQuery("home", async (ctx) => { await ctx.answerCallbackQuery(); await show(ctx, home()); });
  bot.callbackQuery(/^cat:(\d+)$/, async (ctx) => { await ctx.answerCallbackQuery(); await show(ctx, catalog(Number(ctx.match[1]))); });
  bot.callbackQuery(/^item:(\d+):(\d+)$/, async (ctx) => {
    const item = ITEMS.get(Number(ctx.match[1]));
    if (!item) {
      await ctx.answerCallbackQuery({ text: "This item is no longer available." });
      await show(ctx, home());
      return;
    }
    await ctx.answerCallbackQuery();
    await show(ctx, [`<b>${escapeHtml(item[0])}</b>\nPrice: ${item[1]} Stars`,
      new InlineKeyboard().text(`Buy for ${item[1]} Stars`, `buy:${ctx.match[1]}`).row().text("Back", `cat:${ctx.match[2]}`)]);
  });
  bot.callbackQuery(/^buy:(\d+)$/, async (ctx) => {
    const [name, amount] = ITEMS.get(Number(ctx.match[1]));
    await ctx.answerCallbackQuery();
    await ctx.replyWithInvoice(name, "Editable document template", `order-${ctx.match[1]}`, "XTR", [{ label: "Template", amount }]);
  });
  bot.callbackQuery("settings", async (ctx) => { await ctx.answerCallbackQuery(); await show(ctx, settingsView(alertsOf(ctx))); });
  bot.callbackQuery("alerts", async (ctx) => {
    alerts.set(ctx.from.id, !alertsOf(ctx));
    await ctx.answerCallbackQuery({ text: "Saved" });
    await show(ctx, settingsView(alertsOf(ctx)));
  });
  bot.callbackQuery("reset:ask", async (ctx) => {
    await ctx.answerCallbackQuery();
    await show(ctx, ["<b>Reset settings?</b>\nAlerts return to On.",
      new InlineKeyboard().text("Keep settings", "settings").row().text("Reset settings now", "reset:confirm")]);
  });
  bot.callbackQuery("reset:confirm", async (ctx) => {
    alerts.delete(ctx.from.id);
    await ctx.answerCallbackQuery({ text: "Settings reset" });
    await show(ctx, settingsView(true));
  });
  bot.on("callback_query:data", async (ctx) => { await ctx.answerCallbackQuery({ text: "This menu expired." }); await show(ctx, home()); });

  bot.on("pre_checkout_query", async (ctx) => {
    const query = ctx.preCheckoutQuery;
    const item = ITEMS.get(Number(query.invoice_payload.split("-")[1]));
    if (!item || query.total_amount !== item[1]) await ctx.answerPreCheckoutQuery(false, { error_message: "This price changed. Open the catalog and try again." });
    else await ctx.answerPreCheckoutQuery(true);
  });
  bot.on("message:successful_payment", async (ctx) => {
    const payment = ctx.message.successful_payment;
    await ctx.reply(`<b>Receipt</b>\nPaid: ${payment.total_amount} Stars\nRef: <code>${escapeHtml(payment.telegram_payment_charge_id)}</code>\nHelp: /paysupport`, HTML);
  });
  bot.on("message:document", async (ctx) => {
    const { file_name: raw = "file", file_size: size = 0 } = ctx.message.document;
    const name = escapeHtml(raw);
    if (size > MAX_DOWNLOAD) { await ctx.reply(`${name} is too large. I can download files up to 20 MB.`); return; }
    const status = await ctx.reply(`Converting ${name}…`);
    await ctx.replyWithDocument(new InputFile(Buffer.from("CONVERTED"), "converted.txt"), { caption: `Converted ${name}` });
    await ctx.api.deleteMessage(status.chat.id, status.message_id);
  });
  bot.on("message:text", (ctx) => ctx.reply("I need a file or a command. Send /start to open the menu."));
  return bot;
}
