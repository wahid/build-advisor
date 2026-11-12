// A stand-in for the Django API, serving the built frontend: the browser tests
// need predictable answers, not an LLM. Usage: node e2e/mock-server.mjs [port]
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const dist = path.join(path.dirname(fileURLToPath(import.meta.url)), "..", "dist");
const port = Number(process.argv[2] ?? 4321);
const WIKI = "https://www.poewiki.net/wiki/";
const source = (number, title, section, doc_type = "mechanic") => ({
  number, title, section, url: WIKI + title.replace(/ /g, "_"), patch: "3.29.3c", doc_type,
});
let lastAsk = null;

const ANSWER = {
  sources: [source(1, "Poison", "Mechanics"), source(2, "Bleeding", "Mechanics > Damage"), source(3, "Lethal Dose Support", "", "gem")],
  text:
    "**Short answer:** poisons stack without limit [1], while only the strongest bleed counts [2].\n\n" +
    "| Ailment | Stacks? |\n|---|---|\n| Poison | Yes |\n| Bleed | No |\n\n" +
    "Lethal Dose Support adds more poisons [3]. Crimson Dance changes bleed (general game knowledge).",
  entities: [{ name: "Lethal Dose Support", doc_type: "gem", url: WIKI + "Lethal_Dose_Support", summary: "Support, Chaos, Poison. Inflicts additional poisons." }],
};

const COMPARISON = {
  a: { mainSkill: "Tornado Shot", ascendancy: "Slayer", level: 99 },
  b: { mainSkill: "Tornado Shot", ascendancy: "Slayer", level: 99 },
  rows: [
    { stat: "CombinedDPS", label: "DPS (main skill, with ailments)", a: 13078399, b: 8363840, change_pct: -36.0, higher_is_better: true },
    { stat: "Life", label: "Life", a: 4632, b: 4632, change_pct: 0, higher_is_better: true },
  ],
};

const STATS = {
  evals: { meta: "", cases: 60, "hit@8": 1.0, mrr: 0.89, pass_rate: 0.96, grounded: 4.48, relevant: 4.96, admits_gap: 1.0 },
  usage: { days: 30, answers: 412, median_first_word_ms: 3400, median_answer_ms: 12800, average_cost_usd: 0.0019, helpful_share: 0.86, rated: 57 },
  corpus: { pages: 2952, chunks: 27377, patch: "3.29.3d", by_type: { gem: 827 } },
  model: "deepseek-flash",
  web_search: true,
};

function json(res, status, body) {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}

async function readBody(req) {
  let body = "";
  for await (const chunk of req) body += chunk;
  return body ? JSON.parse(body) : {};
}

http
  .createServer(async (req, res) => {
    if (req.method === "POST" && req.url === "/api/ask/") {
      const body = await readBody(req);
      lastAsk = body;
      if (body.question.includes("LIMIT")) {
        return json(res, 429, { code: "daily_limit", detail: "The demo has reached today's limit.", resets_at: new Date(Date.now() + 3 * 3600_000).toISOString() });
      }
      res.writeHead(200, { "Content-Type": "text/event-stream" });
      const send = (event) => res.write(`event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`);
      send({ type: "rewrite", terms: "Poison, Bleeding", tools: false });
      if (body.compare_build) {
        send({ type: "tool_call", id: "compare-build", name: "compare_builds", arguments: {} });
        send({ type: "tool_result", id: "compare-build", name: "compare_builds", ok: true, error: "" });
        send({ type: "comparison", ...COMPARISON });
      }
      send({ type: "sources", sources: ANSWER.sources });
      for (const part of ANSWER.text.match(/[\s\S]{1,30}/g)) send({ type: "delta", text: part });
      send({ type: "done", cited: [1, 2, 3], patch: "3.29.3c", log_id: "log-1", entities: ANSWER.entities });
      return res.end();
    }
    if (req.method === "POST" && req.url === "/api/feedback/") return json(res, 200, { ok: true });
    if (req.url === "/api/stats/") return json(res, 200, STATS);
    if (req.url === "/api/__last__") return json(res, 200, lastAsk);

    const url = req.url.split("?")[0].replace(/^\/static/, "");
    let file = path.join(dist, url === "/" ? "index.html" : url);
    if (!file.startsWith(dist) || !fs.existsSync(file) || fs.statSync(file).isDirectory()) {
      file = path.join(dist, "index.html"); // the app handles its own routes
    }
    const types = { ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png" };
    res.writeHead(200, { "Content-Type": types[path.extname(file)] ?? "text/html" });
    fs.createReadStream(file).pipe(res);
  })
  .listen(port, () => console.log(`mock API on http://localhost:${port}`));
