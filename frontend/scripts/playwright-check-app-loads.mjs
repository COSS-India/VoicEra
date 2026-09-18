// Confirms the app itself doesn't crash/console-error on load with the new
// translate-feature code compiled in — backend isn't running in this
// environment so this can't reach an authenticated call-detail view, but it
// does catch build/hydration errors in layout.tsx (Origin-Trial meta tags)
// and any page that imports the new lib/chrome-translation.ts or
// CallDetailSheet.tsx changes at module-load time.
import { chromium } from "playwright";

const BASE_URL = "http://localhost:3000";
const consoleErrors = [];
const pageErrors = [];

const browser = await chromium.launch();
const page = await browser.newPage();
page.on("console", (msg) => {
  if (msg.type() === "error") consoleErrors.push(msg.text());
});
page.on("pageerror", (err) => pageErrors.push(err.message));

const response = await page.goto(BASE_URL, { waitUntil: "networkidle" });
const status = response.status();
const title = await page.title();

console.log(`GET / -> ${status}, title: "${title}"`);

const relevantConsoleErrors = consoleErrors.filter(
  (e) => !e.includes("Failed to load resource") && !e.includes("favicon"),
);

if (relevantConsoleErrors.length > 0) {
  console.error("Console errors found:");
  relevantConsoleErrors.forEach((e) => console.error("  -", e));
}
if (pageErrors.length > 0) {
  console.error("Uncaught page errors found:");
  pageErrors.forEach((e) => console.error("  -", e));
}

await browser.close();

const ok = status < 500 && relevantConsoleErrors.length === 0 && pageErrors.length === 0;
console.log(ok ? "PASS: app loads with no console/page errors" : "FAIL: see errors above");
process.exit(ok ? 0 : 1);
