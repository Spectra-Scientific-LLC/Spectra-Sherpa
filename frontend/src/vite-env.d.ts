/// <reference types="vite/client" />

declare module 'plotly.js-cartesian-dist-min' {
  export * from 'plotly.js';
}

// Build-time-injected frontend bundle version, read from package.json
// at vite build.  See vite.config.ts `define`.
declare const __SHERPA_FRONTEND_VERSION__: string;
