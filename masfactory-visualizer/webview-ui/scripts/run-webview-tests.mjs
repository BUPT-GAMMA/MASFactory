import { mkdir, rm } from 'node:fs/promises';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { build } from 'esbuild';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const outDir = resolve(root, '.tmp-tests');
const outfile = resolve(outDir, 'vibeStore.aml.test.mjs');

await rm(outDir, { recursive: true, force: true });
await mkdir(outDir, { recursive: true });

await build({
  entryPoints: [resolve(root, 'test-src/vibeStore.aml.test.ts')],
  outfile,
  bundle: true,
  platform: 'node',
  format: 'esm',
  target: 'node20',
  sourcemap: 'inline',
  alias: {
    '@shared': resolve(root, '../src/shared')
  }
});

try {
  await import(`file://${outfile}`);
} finally {
  await rm(outDir, { recursive: true, force: true });
}
