import { viteCommonjs } from '@originjs/vite-plugin-commonjs';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [viteCommonjs()],
  resolve: {
    // dcmjs imports xmlbuilder2's Node entry, whose `events` dependency Vite
    // externalizes to an empty browser module. The package's UMD build already
    // contains the required browser-safe EventEmitter and URL shims.
    alias: {
      xmlbuilder2: 'xmlbuilder2/lib/xmlbuilder2.min.js',
    },
  },
  optimizeDeps: {
    exclude: ['@cornerstonejs/dicom-image-loader'],
    // The loader imports jpeg-lossless dynamically, so list it explicitly.
    // Vite then emits a valid optimized source map instead of following the
    // package's dangling release/lossless.js.map reference during development.
    include: ['dicom-parser', 'jpeg-lossless-decoder-js'],
  },
  worker: {
    format: 'es',
  },
  test: {
    environment: 'node',
    include: ['src/tests/**/*.test.ts'],
  },
});
