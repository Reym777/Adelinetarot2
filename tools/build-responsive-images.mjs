import { promises as fs } from 'node:fs';
import path from 'node:path';
import sharp from 'sharp';

const root = process.cwd();
const siteRoot = path.basename(root).toLowerCase() === 'adelinemagica' ? root : path.join(root, 'Adelinemagica');

const jobs = [
  {
    file: 'assets/images/bandeau10_upscaled_1280_11zon.webp',
    widths: [480, 768, 1024, 1280],
    quality: 74
  },
  {
    file: 'assets/images/meditacion-PAQUETE_13_11zon.webp',
    widths: [180, 260, 320, 520],
    quality: 76
  },
  {
    file: 'assets/images/livre-PAQUETE_10_11zon.webp',
    widths: [180, 260, 320, 520],
    quality: 76
  },
  {
    file: 'assets/images/carte-PAQUETE_6_11zon.webp',
    widths: [180, 260, 320, 520],
    quality: 76
  }
];

function withWidthSuffix(file, width) {
  const ext = path.extname(file);
  const base = file.slice(0, -ext.length);
  return `${base}-${width}w${ext}`;
}

async function generateVariants() {
  for (const job of jobs) {
    const inputAbs = path.join(siteRoot, job.file);
    const source = sharp(inputAbs, { failOn: 'none' });
    const meta = await source.metadata();
    const sourceWidth = meta.width || Math.max(...job.widths);

    for (const width of job.widths) {
      const targetWidth = Math.min(width, sourceWidth);
      const outRel = withWidthSuffix(job.file, targetWidth);
      const outAbs = path.join(siteRoot, outRel);

      await sharp(inputAbs, { failOn: 'none' })
        .resize({ width: targetWidth, withoutEnlargement: true })
        .webp({ quality: job.quality })
        .toFile(outAbs);

      console.log(`generated ${path.relative(siteRoot, outAbs)}`);
    }
  }
}

function rewriteImgTags(html) {
  let out = html;

  out = out.replace(
    /src="([^"]*?)bandeau10_upscaled_1280_11zon\.webp"\s+srcset="[^"]*"/g,
    (_m, prefix) => `src="${prefix}bandeau10_upscaled_1280_11zon-768w.webp" srcset="${prefix}bandeau10_upscaled_1280_11zon-480w.webp 480w, ${prefix}bandeau10_upscaled_1280_11zon-768w.webp 768w, ${prefix}bandeau10_upscaled_1280_11zon-1024w.webp 1024w, ${prefix}bandeau10_upscaled_1280_11zon-1280w.webp 1280w"`
  );

  out = out.replace(
    /href="([^"]*?)bandeau10_upscaled_1280_11zon\.webp"\s+imagesrcset="[^"]*"/g,
    (_m, prefix) => `href="${prefix}bandeau10_upscaled_1280_11zon-768w.webp" imagesrcset="${prefix}bandeau10_upscaled_1280_11zon-480w.webp 480w, ${prefix}bandeau10_upscaled_1280_11zon-768w.webp 768w, ${prefix}bandeau10_upscaled_1280_11zon-1024w.webp 1024w, ${prefix}bandeau10_upscaled_1280_11zon-1280w.webp 1280w"`
  );

  const packageDefs = [
    {
      name: 'meditacion-PAQUETE_13_11zon',
      sizes: '(max-width: 768px) 42vw, 180px'
    },
    {
      name: 'livre-PAQUETE_10_11zon',
      sizes: '(max-width: 768px) 42vw, 180px'
    },
    {
      name: 'carte-PAQUETE_6_11zon',
      sizes: '(max-width: 768px) 42vw, 180px'
    }
  ];

  for (const def of packageDefs) {
    const re = new RegExp(`src=\"([^\"]*?)${def.name}\\.webp\"`, 'g');
    out = out.replace(re, (_m, prefix) => {
      return `src="${prefix}${def.name}-260w.webp" srcset="${prefix}${def.name}-180w.webp 180w, ${prefix}${def.name}-260w.webp 260w, ${prefix}${def.name}-320w.webp 320w, ${prefix}${def.name}-520w.webp 520w" sizes="${def.sizes}"`;
    });
  }

  return out;
}

async function rewriteHtml() {
  const htmlFiles = [];

  async function walk(dir) {
    const entries = await fs.readdir(dir, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.name === 'node_modules') continue;
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        await walk(full);
        continue;
      }
      if (entry.isFile() && entry.name.toLowerCase().endsWith('.html')) {
        htmlFiles.push(full);
      }
    }
  }

  await walk(siteRoot);

  for (const file of htmlFiles) {
    const before = await fs.readFile(file, 'utf8');
    const after = rewriteImgTags(before);
    if (after !== before) {
      await fs.writeFile(file, after, 'utf8');
      console.log(`updated ${path.relative(siteRoot, file)}`);
    }
  }
}

await generateVariants();
await rewriteHtml();
console.log('Responsive images done.');
