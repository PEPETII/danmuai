// Generate in memory so --check never repairs or rewrites a stale artifact.
import { readFile, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { parseArgs } from 'node:util';
import postcss from 'postcss';
import tailwindcss from 'tailwindcss';
import config from '../tailwind.config.cjs';

const root = fileURLToPath(new URL('../', import.meta.url));
const { values } = parseArgs({ options: { check: { type: 'boolean' }, output: { type: 'string' } } });
const input = path.join(root, 'web/static/utilities.input.css');
const output = values.output ? path.resolve(values.output) : path.join(root, 'web/static/utilities.css');
// Content resolution is independent of the caller's working directory.
config.content = config.content.map(pattern => path.join(root, pattern));
const result = await postcss([tailwindcss(config)]).process(await readFile(input, 'utf8'), {
  from: input, to: output, map: false,
});
const css = result.css.replaceAll('\r\n', '\n');
if (values.check) {
  const current = await readFile(output, 'utf8').catch(error => {
    if (error.code === 'ENOENT') return null;
    throw error;
  });
  if (current?.replaceAll('\r\n', '\n') !== css) {
    console.error('utilities.css is stale; run npm run build:css.');
    process.exitCode = 1;
  } else {
    console.log('utilities.css matches its sources.');
  }
} else {
  await writeFile(output, css, 'utf8');
  console.log(`Generated utilities.css (${Buffer.byteLength(css)} bytes).`);
}
