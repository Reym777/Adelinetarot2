import { promises as fs } from 'node:fs';
import path from 'node:path';
import { transform } from 'esbuild';

const cwd = process.cwd();
const targetDir = path.basename(cwd).toLowerCase() === 'adelinemagica'
  ? cwd
  : path.join(cwd, 'Adelinemagica');

function shouldSkipScriptTag(attrs) {
  if (/\bsrc\s*=/.test(attrs)) return true;
  const typeMatch = attrs.match(/\btype\s*=\s*(["'])(.*?)\1/i);
  if (!typeMatch) return false;
  const type = String(typeMatch[2] || '').toLowerCase();
  return type.includes('application/ld+json');
}

function isLikelyJs(code) {
  const trimmed = code.trim();
  if (!trimmed) return false;
  if (trimmed.startsWith('{') && trimmed.endsWith('}')) return true;
  return true;
}

async function minifyInlineScriptsInFile(filePath) {
  const original = await fs.readFile(filePath, 'utf8');
  const re = /<script\b([^>]*)>([\s\S]*?)<\/script>/gi;

  let changed = false;
  let scriptCount = 0;
  let out = '';
  let cursor = 0;
  let match;

  while ((match = re.exec(original)) !== null) {
    const full = match[0];
    const attrs = match[1] || '';
    const code = match[2] || '';

    out += original.slice(cursor, match.index);

    if (shouldSkipScriptTag(attrs) || !isLikelyJs(code)) {
      out += full;
      cursor = re.lastIndex;
      continue;
    }

    try {
      const minified = await transform(code, {
        loader: 'js',
        minify: true,
        legalComments: 'none',
        target: 'es2018'
      });
      const next = `<script${attrs}>${minified.code}</script>`;
      out += next;
      cursor = re.lastIndex;
      if (next !== full) {
        changed = true;
        scriptCount += 1;
      }
    } catch {
      out += full;
      cursor = re.lastIndex;
    }
  }

  out += original.slice(cursor);

  if (changed) {
    await fs.writeFile(filePath, out, 'utf8');
  }

  return { changed, scriptCount };
}

async function collectHtmlFiles(dir) {
  const out = [];
  const entries = await fs.readdir(dir, { withFileTypes: true });
  for (const entry of entries) {
    if (entry.name === 'node_modules') continue;
    const fullPath = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...(await collectHtmlFiles(fullPath)));
      continue;
    }
    if (entry.isFile() && entry.name.toLowerCase().endsWith('.html')) {
      out.push(fullPath);
    }
  }
  return out;
}

async function main() {
  const htmlFiles = await collectHtmlFiles(targetDir);

  let changedFiles = 0;
  let changedScripts = 0;

  for (const filePath of htmlFiles) {
    const res = await minifyInlineScriptsInFile(filePath);
    if (res.changed) {
      changedFiles += 1;
      changedScripts += res.scriptCount;
      console.log(`Minified inline scripts in ${path.basename(filePath)} (${res.scriptCount})`);
    }
  }

  console.log(`Done. Files changed: ${changedFiles}, inline scripts minified: ${changedScripts}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
