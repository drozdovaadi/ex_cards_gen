#!/usr/bin/env node
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const markedModule = await import(pathToFileURL(require.resolve("marked")).href);
const { marked } = markedModule;

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const defaultInputDir = path.join(projectRoot, "output", "exercise_cards");
const defaultOutputDir = path.join(projectRoot, "output", "pdf", "exercise_cards");

function parseArgs(argv) {
  const args = {
    inputDir: defaultInputDir,
    outputDir: defaultOutputDir,
    all: false,
    file: null,
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--all") args.all = true;
    else if (arg === "--file") args.file = argv[++i];
    else if (arg === "--input-dir") args.inputDir = argv[++i];
    else if (arg === "--output-dir") args.outputDir = argv[++i];
    else throw new Error(`Unknown argument: ${arg}`);
  }
  if (!args.all && !args.file) throw new Error("Use --all or --file.");
  return args;
}

function htmlDocument(markdown, sourcePath) {
  const html = marked.parse(markdown, { gfm: true, breaks: false });
  const source = sourcePath.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
  return `<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <style>
    @page { size: A3 landscape; margin: 12mm; }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      color: #111827;
      font-family: "Segoe UI", Arial, sans-serif;
      font-size: 9.5px;
      line-height: 1.34;
      background: white;
    }
    main { width: 100%; }
    h1, h2, h3, h4, h5 {
      color: #111827;
      line-height: 1.18;
      margin: 0 0 8px;
      page-break-after: avoid;
      break-after: avoid;
    }
    h1 {
      font-size: 22px;
      padding-bottom: 7px;
      border-bottom: 2px solid #111827;
      margin-bottom: 10px;
    }
    h2 {
      font-size: 15px;
      padding-top: 10px;
      margin-top: 12px;
      border-top: 1px solid #cbd5e1;
    }
    h3 { font-size: 12px; margin-top: 10px; }
    h4, h5 { font-size: 10px; margin-top: 8px; color: #334155; }
    p { margin: 0 0 8px; }
    code {
      font-family: Consolas, "Courier New", monospace;
      font-size: 8.5px;
      color: #334155;
      word-break: break-all;
    }
    table {
      width: 100%;
      border-collapse: collapse;
      table-layout: fixed;
      margin: 0 0 10px;
      page-break-inside: auto;
    }
    thead { display: table-header-group; }
    tr { page-break-inside: avoid; break-inside: avoid; }
    th, td {
      border: 1px solid #d1d5db;
      padding: 4px 5px;
      vertical-align: top;
      overflow-wrap: anywhere;
      word-break: break-word;
    }
    th {
      background: #f3f4f6;
      color: #111827;
      font-weight: 650;
    }
    td { background: #ffffff; }
    tbody tr:nth-child(even) td { background: #fafafa; }
    .source {
      font-size: 8.5px;
      color: #475569;
      margin-bottom: 12px;
    }
  </style>
</head>
<body>
  <main>
    <div class="source">${source}</div>
    ${html}
  </main>
</body>
</html>`;
}

async function listMarkdownFiles(inputDir, file, all) {
  if (file) return [path.resolve(file)];
  if (!all) return [];
  const entries = await fs.readdir(inputDir, { withFileTypes: true });
  return entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(".md"))
    .map((entry) => path.join(inputDir, entry.name))
    .sort((a, b) => a.localeCompare(b));
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  await fs.mkdir(args.outputDir, { recursive: true });
  const files = await listMarkdownFiles(args.inputDir, args.file, args.all);

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  const rendered = [];
  for (const file of files) {
    const markdown = await fs.readFile(file, "utf8");
    const target = path.join(args.outputDir, `${path.basename(file, ".md")}.pdf`);
    await page.setContent(htmlDocument(markdown, file), { waitUntil: "load" });
    await page.pdf({
      path: target,
      format: "A3",
      landscape: true,
      printBackground: true,
      margin: { top: "12mm", right: "12mm", bottom: "12mm", left: "12mm" },
      preferCSSPageSize: true,
    });
    rendered.push(target);
  }
  await browser.close();
  console.log(JSON.stringify({ rendered, count: rendered.length }, null, 2));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
