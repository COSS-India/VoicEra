// Standalone Playwright script (not part of the vitest suite) that loads a
// real Chromium browser and exercises chrome-translation.ts against actual
// window globals, catching real-browser issues (namespace shape, async
// timing, exception propagation) that Node-based vitest mocks can't. Backend
// isn't running in this environment, so this checks the module's browser
// behavior in isolation rather than the full CallDetailSheet UI flow.
import { chromium } from "playwright";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { readFileSync } from "node:fs";
import ts from "typescript";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");

// Strip types with the TypeScript compiler API (already a project dependency
// via Next.js) so chrome-translation.ts can run directly in a real browser
// page without needing a bundler — this file has no imports of its own, so a
// plain transpile (no module resolution) is enough.
function compileToBrowserJs(tsPath) {
  const source = readFileSync(tsPath, "utf-8");
  const result = ts.transpileModule(source, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2020,
      module: ts.ModuleKind.ESNext,
    },
  });
  return result.outputText;
}

const moduleJs = compileToBrowserJs(path.join(repoRoot, "src/lib/chrome-translation.ts"));

const results = [];
function record(name, pass, detail) {
  results.push({ name, pass, detail });
  console.log(`${pass ? "PASS" : "FAIL"}: ${name}${detail ? " — " + detail : ""}`);
}

const browser = await chromium.launch();
const page = await browser.newPage();

// Serve the compiled module inline via a data URL page so it runs in a real
// browser JS engine (real Promise microtask timing, real globalThis).
await page.setContent(`<!doctype html><html><body><script type="module">${moduleJs}
window.__mod = { isChromeTranslationAvailable, detectTextLanguage, isTranslationPairAvailable, translateLines };
window.__ready = true;
</script></body></html>`);

await page.waitForFunction(() => window.__ready === true);

// --- Test 1: no Chrome API present in a real browser context ---
{
  const available = await page.evaluate(() => window.__mod.isChromeTranslationAvailable());
  record("isChromeTranslationAvailable() is false with no Chrome API present", available === false);
}

// --- Test 2: with a fake Translator global (class-shaped), availability flips true ---
{
  await page.evaluate(() => {
    window.Translator = {
      availability: async () => "available",
      create: async () => ({
        translate: async (t) => `[translated:${t}]`,
        destroy: () => {},
      }),
    };
  });
  const available = await page.evaluate(() => window.__mod.isChromeTranslationAvailable());
  record("isChromeTranslationAvailable() is true once window.Translator is set", available === true);
}

// --- Test 3: isTranslationPairAvailable reflects the fake API's availability() ---
{
  const pairOk = await page.evaluate(() => window.__mod.isTranslationPairAvailable("hi", "en"));
  record("isTranslationPairAvailable() returns true for a supported pair", pairOk === true);
}

// --- Test 4: translateLines actually round-trips through the real browser Promise chain ---
{
  const lines = await page.evaluate(() =>
    window.__mod.translateLines(["hello", "", "world"], "en", "hi"),
  );
  record(
    "translateLines() translates non-blank lines, passes blank lines through",
    JSON.stringify(lines) === JSON.stringify(["[translated:hello]", "", "[translated:world]"]),
    JSON.stringify(lines),
  );
}

// --- Test 5: detectTextLanguage with a fake LanguageDetector global ---
{
  await page.evaluate(() => {
    window.LanguageDetector = {
      create: async () => ({
        detect: async () => [{ detectedLanguage: "hi", confidence: 0.95 }],
        destroy: () => {},
      }),
    };
  });
  const detected = await page.evaluate(() => window.__mod.detectTextLanguage("नमस्ते"));
  record(
    "detectTextLanguage() returns the detected language from a real browser Promise chain",
    detected && detected.language === "hi" && detected.confidence === 0.95,
    JSON.stringify(detected),
  );
}

// --- Test 6: translateLines throws a real Error (not silently resolves) when API is absent ---
{
  await page.evaluate(() => {
    delete window.Translator;
  });
  const threw = await page.evaluate(async () => {
    try {
      await window.__mod.translateLines(["x"], "en", "hi");
      return false;
    } catch (e) {
      return e instanceof Error && e.message.includes("not available");
    }
  });
  record("translateLines() throws a real Error when Translator API is removed", threw === true);
}

await browser.close();

const failed = results.filter((r) => !r.pass);
console.log(`\n${results.length - failed.length}/${results.length} checks passed.`);
if (failed.length > 0) {
  console.error(`${failed.length} FAILED CHECK(S):`, failed.map((f) => f.name));
  process.exit(1);
}
process.exit(0);
