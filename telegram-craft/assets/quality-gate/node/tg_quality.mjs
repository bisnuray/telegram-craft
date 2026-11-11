// Capture real outgoing Telegram calls from a grammY bot, with no network.
// Validation runs in lint_core.py, the same code the Python adapters use.
import { spawnSync } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { after } from "node:test";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const BOT_INFO = {
  id: 999, is_bot: true, first_name: "Test Bot", username: "test_bot", can_join_groups: true,
  can_read_all_group_messages: false, supports_inline_queries: false, can_connect_to_business: false,
  has_main_web_app: false, has_topics_enabled: false, allows_users_to_create_topics: false,
};
const SEND = /^(sendMessage|sendPhoto|sendVideo|sendAudio|sendDocument|sendAnimation|sendVoice|sendVideoNote|sendSticker|sendInvoice|sendLocation|sendContact|sendPoll|sendDice|sendRichMessage|copyMessage)/;

export class Recorder {
  framework = "grammy";
  interactions = [];
  scenario = "default";
  current = null;

  begin(kind, value, chatType, flags = {}) {
    this.current = { scenario: this.scenario, kind, value, chat_type: chatType, calls: [], ...flags };
    this.interactions.push(this.current);
    return this.current;
  }

  save(directory = ".tg-lint") {
    mkdirSync(directory, { recursive: true });
    const path = join(directory, `capture-${process.pid}.json`);
    writeFileSync(path, JSON.stringify({ version: 1, framework: this.framework, interactions: this.interactions }, null, 1));
    return path;
  }
}

/** Lint what was captured. Returns the result; `throwOnFail` fails the run. */
export function runGate(recorder, { directory = process.env.TG_LINT_DIR ?? ".tg-lint", throwOnFail = true } = {}) {
  if (!recorder.interactions.length) {
    if (process.env.TG_LINT_REQUIRE_INTERACTIONS === "1" && throwOnFail) throw new Error("no Telegram interactions were captured");
    return null;
  }
  const capture = recorder.save(directory);
  const report = join(directory, `report-${process.pid}.json`);
  const args = [join(here, "lint_core.py"), "--capture", capture, "--report", report];
  if (process.env.TG_LINT_STRICT === "1") args.push("--strict");
  if (process.env.TG_LINT_MIN_BUTTON_COVERAGE) args.push("--min-button-coverage", process.env.TG_LINT_MIN_BUTTON_COVERAGE);
  if (process.env.TG_LINT_SOURCE !== "0") args.push("--source", process.cwd());
  if (process.env.TG_LINT_REQUIRE_COVERAGE === "1") args.push("--require-coverage");
  const run = spawnSync(process.env.PYTHON ?? "python3", args, { encoding: "utf8" });
  if (run.error) throw new Error(`could not run Python for lint_core.py: ${run.error.message}`);
  console.log(run.stdout);
  if (run.status !== 0 && throwOnFail) throw new Error(`Telegram quality gate failed (exit ${run.status})\n${run.stdout}${run.stderr}`);
  return run;
}

/** Call once per test file. Runs the gate after that file's tests. */
export function installLintGate(recorder, options) {
  after(() => { runGate(recorder, options); });
}

// grammY's InputFile throws from toJSON, so copy by hand instead of JSON.stringify.
function safe(value) {
  if (value === undefined || typeof value === "function") return undefined;
  if (value === null || typeof value !== "object") return value;
  if (value.constructor?.name === "InputFile") return "<InputFile>";
  if (Array.isArray(value)) return value.map(safe);
  if (typeof value.toJSON === "function") return safe(value.toJSON());
  return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, safe(v)]).filter(([, v]) => v !== undefined));
}

export class GrammyHarness {
  framework = "grammy";
  calls = [];
  responses = new Map();
  failures = new Map();
  keyboard = [];
  keyboardMessageId = null;
  ids = { message: 100, update: 1, callback: 1 };

  constructor(bot, recorder, { userId = 1000, chatId, chatType = "private" } = {}) {
    Object.assign(this, { bot, recorder, userId, chatType });
    this.chatId = chatId ?? (chatType === "private" ? userId : -100123);
    bot.botInfo = BOT_INFO;
    bot.api.config.use((_prev, method, payload) => this.#handle(method, safe(payload ?? {})));
  }

  async scenario(name, body) {
    const previous = this.recorder.scenario;
    this.recorder.scenario = name;
    try { await body(this); } finally { this.recorder.scenario = previous; }
  }

  respond(method, result) { this.responses.set(method, result); }
  failNext(method, description, errorCode = 400) {
    this.failures.set(method, [...(this.failures.get(method) ?? []), { description, error_code: errorCode }]);
  }
  get labels() { return this.keyboard.flat().map((b) => b.text); }
  sent(method) { return this.calls.filter((c) => c.method === method).map((c) => c.params); }
  get lastText() {
    for (const call of [...this.calls].reverse()) if (call.params.text && call.method !== "answerCallbackQuery") return call.params.text;
    return null;
  }

  async command(text, flags = {}) {
    const entities = [{ type: "bot_command", offset: 0, length: text.split(" ")[0].length }];
    await this.#run("command", text, { message: this.#message({ text, entities }) }, flags);
  }
  async text(text, flags = {}) { await this.#run("text", text, { message: this.#message({ text }) }, flags); }
  async press(label) {
    const button = this.keyboard.flat().find((b) => b.text === label);
    if (!button) throw new Error(`no button "${label}" on the current keyboard; visible: ${this.labels}`);
    if (!button.callback_data) throw new Error(`"${label}" is not a callback button`);
    await this.callback(button.callback_data);
  }
  async callback(data, { expected_error, userId } = {}) {
    this.ids.callback += 1;
    const message = this.#message({ text: "previous", message_id: this.keyboardMessageId ?? ++this.ids.message, from: BOT_INFO });
    const query = { id: String(this.ids.callback), from: this.#user(userId ?? this.userId), chat_instance: "ci", data, message };
    await this.#run("callback", data, { callback_query: query }, { expected_error });
  }
  async media(field, attachment, flags = {}) {
    const file = { file_id: "f1", file_unique_id: "u1", ...attachment };
    await this.#run("media", field, { message: this.#message({ [field]: field === "photo" ? [file] : file }) }, flags);
  }
  async preCheckout(payload, total, currency = "XTR") {
    const query = { id: "pc1", from: this.#user(this.userId), currency, total_amount: total, invoice_payload: payload };
    await this.#run("pre_checkout", payload, { pre_checkout_query: query });
  }
  async successfulPayment(payload, total, chargeId = "charge-1", currency = "XTR") {
    const successful_payment = { currency, total_amount: total, invoice_payload: payload, telegram_payment_charge_id: chargeId, provider_payment_charge_id: "" };
    await this.#run("payment", payload, { message: this.#message({ successful_payment }) });
  }

  #user(id) { return { id, is_bot: false, first_name: "Test", language_code: "en" }; }
  #chat() { return this.chatType === "private" ? { id: this.chatId, type: "private", first_name: "Test" } : { id: this.chatId, type: this.chatType, title: "Test chat" }; }
  #message(fields) { return { message_id: ++this.ids.message, date: Math.floor(Date.now() / 1000), chat: this.#chat(), from: this.#user(this.userId), ...fields }; }

  async #run(kind, value, payload, flags = {}) {
    const clean = Object.fromEntries(Object.entries(flags).filter(([, v]) => v));
    const record = this.recorder.begin(kind, value, this.chatType, clean);
    try {
      await this.bot.handleUpdate({ update_id: ++this.ids.update, ...payload });
    } catch (error) {
      record.error = `${error.name}: ${error.message}`;
      if (!flags.expected_error) throw error;
    }
  }

  #handle(method, params) {
    const call = { method, params };
    this.calls.push(call);
    this.recorder.current?.calls.push(call);
    const queued = this.failures.get(method);
    if (queued?.length) return { ok: false, ...queued.shift() };
    const result = this.responses.has(method) ? this.responses.get(method) : this.#result(method, params);
    this.#track(method, params, result);
    return { ok: true, result };
  }

  #botMessage(id, text) { return this.#message({ ...(id ? { message_id: id } : {}), text: typeof text === "string" ? text : "ok", from: BOT_INFO }); }
  #result(method, params) {
    if (method === "getFile") return { file_id: params.file_id ?? "f1", file_unique_id: "u1", file_size: 9, file_path: "files/test" };
    if (method === "createInvoiceLink") return "https://t.me/$test_invoice";
    if (method === "sendMediaGroup") return params.media.map(() => this.#botMessage());
    if (method.startsWith("edit")) return this.#botMessage(params.message_id, params.text);
    if (SEND.test(method)) return this.#botMessage(undefined, params.text ?? params.caption);
    return true;
  }
  #track(method, params, result) {
    if (!SEND.test(method) && !method.startsWith("edit")) return;
    const rows = params.reply_markup?.inline_keyboard;
    if (rows) { this.keyboard = rows; this.keyboardMessageId = result?.message_id ?? null; }
    else if (method.startsWith("edit") && params.message_id === this.keyboardMessageId) this.keyboard = [];
  }
}
