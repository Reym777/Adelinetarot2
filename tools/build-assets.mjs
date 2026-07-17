import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { transform } from 'esbuild';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const root = path.resolve(__dirname, '..');

const assets = [
  'assets/styles.css',
  'assets/site.js',
  'assets/i18n.js',
  'assets/admin.js',
  'assets/app.js',
  'assets/portal.js',
  'assets/fullcalendar-slot-picker.js',
  'assets/natal-descriptions.js'
];

for (const relPath of assets) {
  const absPath = path.resolve(root, relPath);
  const source = await readFile(absPath, 'utf8');
  const ext = path.extname(relPath);
  const loader = ext === '.css' ? 'css' : 'js';
  const dir = path.dirname(absPath);
  const base = path.basename(absPath, ext);
  const outPath = path.join(dir, `${base}.min${ext}`);

  try {
    const result = await transform(source, {
      loader,
      minify: true,
      target: loader === 'js' ? 'es2018' : undefined,
      legalComments: 'none'
    });
    await writeFile(outPath, result.code, 'utf8');
    console.log(`${relPath} -> ${path.relative(root, outPath)}`);
  } catch (error) {
    await writeFile(outPath, source, 'utf8');
    const message = error && error.message ? error.message.split('\n')[0] : 'unknown error';
    console.warn(`warn: fallback without minify for ${relPath} (${message})`);
  }
}
