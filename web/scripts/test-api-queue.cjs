const fs = require("node:fs");
const path = require("node:path");
const assert = require("node:assert/strict");
const ts = require("typescript");
const code = ts.transpileModule(
  fs.readFileSync(path.join(__dirname, "../src/lib/utils.ts"), "utf8"),
  {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
    },
  },
).outputText;
const moduleObject = { exports: {} };
new Function("require", "module", "exports", code)(
  require,
  moduleObject,
  moduleObject.exports,
);
const { api } = moduleObject.exports;
async function main() {
  let active = 0,
    peak = 0,
    count = 0;
  global.fetch = async (url) => {
    active++;
    peak = Math.max(peak, active);
    count++;
    return {
      ok: true,
      json: async () => {
        await new Promise((resolve) => setTimeout(resolve, 5));
        active--;
        return { url };
      },
    };
  };
  const all = await Promise.all(
    Array.from({ length: 8 }, (_, i) => api("/read-" + i)),
  );
  assert.equal(peak, 1);
  assert.equal(count, 8);
  assert.equal(all[7].url, "/api/read-7");
  const pending = api("/active-before-abort");
  const abort = new AbortController();
  abort.abort();
  await assert.rejects(
    api("/aborted", { signal: abort.signal }),
    (error) => error.name === "AbortError",
  );
  await pending;
  assert.equal(count, 9);
  assert.equal((await api("/after-abort")).url, "/api/after-abort");
  global.fetch = async () => {
    throw new TypeError("Failed to fetch");
  };
  await assert.rejects(api("/network-error"), /Failed to fetch/);
  global.fetch = async () => ({
    ok: false,
    status: 429,
    json: async () => ({
      detail: "Synthetic demo request budget reached. Retry shortly.",
    }),
  });
  await assert.rejects(
    api("/budget-error"),
    (error) => error.status === 429 && error.message.includes("HTTP 429"),
  );
  global.fetch = async (url, init) => ({
    ok: true,
    json: async () => ({ url, method: init?.method ?? "GET" }),
  });
  assert.deepEqual(await api("/after-errors"), {
    url: "/api/after-errors",
    method: "GET",
  });
  assert.equal(
    (await api("/unchanged-write", { method: "POST", body: "{}" })).method,
    "POST",
  );
  console.log(
    JSON.stringify({
      read_peak: peak,
      reads: 8,
      aborted_fetches: 0,
      network_and_429_recovery: true,
      writes_unchanged: true,
      passed: true,
    }),
  );
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
