import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve, relative, extname } from 'node:path';
import { pathToFileURL } from 'node:url';

// A migration ratchet, not a claim that legacy literals are acceptable forever.
// Count per file AND literal: removing one color cannot fund an unrelated one.
const authorities = new Set(['assets/tokens.css', 'theme/plotTheme.ts']);
const literals = /#[\da-f]{8}\b|#[\da-f]{6}\b|#[\da-f]{4}\b|#[\da-f]{3}\b|\b(?:rgba?|hsla?)\([^)]*\)/gi;

export function inventoryColors(root) {
  const files = {};
  function walk(folder) {
    for (const entry of readdirSync(folder, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name))) {
      if (['test', 'tests', '__tests__', 'node_modules'].includes(entry.name)) continue;
      const path = resolve(folder, entry.name);
      if (entry.isDirectory()) { walk(path); continue; }
      const name = relative(root, path).replaceAll('\\', '/');
      if (!entry.isFile() || authorities.has(name) || /\.(test|spec)\./.test(name) || !['.css', '.vue', '.ts', '.js'].includes(extname(name))) continue;
      const source = readFileSync(path, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/<!--[^]*?-->/g, '');
      const counts = {};
      for (const match of source.matchAll(literals)) {
        const color = match[0].toLowerCase().replace(/\s+/g, '');
        counts[color] = (counts[color] ?? 0) + 1;
      }
      if (Object.keys(counts).length) files[name] = Object.fromEntries(Object.entries(counts).sort());
    }
  }
  walk(resolve(root));
  return files;
}

export function colorRegressions(current, baseline) {
  const failures = [];
  for (const [file, colors] of Object.entries(current)) {
    for (const [color, count] of Object.entries(colors)) {
      const allowed = baseline[file]?.[color] ?? 0;
      if (count > allowed) failures.push(`${file}: ${color} has ${count} occurrences (baseline ${allowed}); use the shared theme authority.`);
    }
  }
  return failures;
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  const root = resolve(process.argv[2] || 'src');
  const baselinePath = resolve(process.argv[3] || 'theme-color-baseline.json');
  const files = inventoryColors(root);
  if (process.argv.includes('--write')) {
    writeFileSync(baselinePath, JSON.stringify({ schema_version: 1, files }, null, 2) + '\n');
  } else {
    const failures = colorRegressions(files, JSON.parse(readFileSync(baselinePath, 'utf8')).files);
    if (failures.length) { console.error(failures.join('\n')); process.exitCode = 1; }
    else console.log('Theme color ratchet passed. Legacy inventory is not a migration-completion claim.');
  }
}
