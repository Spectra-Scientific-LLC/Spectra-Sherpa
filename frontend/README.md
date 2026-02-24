# SpectraSherpa Frontend

Vue 3 + TypeScript single-page application for the SpectraSherpa spectroscopy platform.

## Quick Start

```bash
npm ci           # install dependencies
npm run dev      # start dev server on http://localhost:5173
```

The dev server proxies `/ws` requests to the backend at `http://127.0.0.1:8000`.
Start the backend first: `make dev` from the repo root runs both together.

## Tech Stack

- **Framework:** Vue 3 Composition API (`<script setup lang="ts">`)
- **State:** Pinia stores
- **UI Library:** PrimeVue 3
- **DAG Canvas:** Vue Flow (`@vue-flow/core`)
- **Charts:** Plotly.js
- **Build:** Vite 5
- **Type Check:** vue-tsc (strict mode)
- **Tests:** Vitest + happy-dom

## Directory Layout

```
src/
├── api/            HTTP client wrappers
├── components/     Reusable UI components (20+ files)
│   ├── data/       Spectra-specific uploaders
│   └── settings/   API token management
├── composables/    Vue composables (shared logic)
├── layouts/        Page layout shells
├── router/         Vue Router config
├── stores/         Pinia stores (13 stores)
├── types/          TypeScript type definitions
├── utils/          Helper modules (12 files)
└── views/          Page-level components
    ├── data/           Dataset explorer
    ├── deploy/         Folder watch & deployment
    ├── experiments/    Experiment management
    ├── project/        Project overview
    ├── report/         Report builder
    ├── settings/       User preferences & API keys
    └── workflow-builder/
        ├── WorkflowCanvas.vue      DAG node/edge canvas
        ├── WorkflowInspector.vue   Node parameter editor
        └── modals/                 File load, blend, plot dialogs
```

## Key Stores

| Store | File | Purpose |
|-------|------|---------|
| `useWorkflowStore` | `stores/workflow.ts` | DAG state, node/edge CRUD, execution |
| `useDataStore` | `stores/data.ts` | Dataset catalog, file inspection |
| `useAuthStore` | `stores/auth.ts` | Login, registration, JWT tokens |
| `useLlmStore` | `stores/llm.ts` | LLM chat, streaming, MCP tool calls |
| `useSherpaStore` | `stores/sherpa.ts` | AI advisor, workflow recommendations |
| `useJobStore` | `stores/job.ts` | Job tracking via WebSocket |

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start HMR dev server (port 5173) |
| `npm run build` | Type-check + production build |
| `npm run test` | Run Vitest tests |
| `npm run lint` | ESLint check (`--max-warnings 0`) |
| `npm run format` | Prettier auto-format |

## Build Output

Vite builds directly into `../src/spectra_sherpa/static/` (not `dist/`).
This is configured in `vite.config.ts`. The built assets are committed to the repo
so the Python package serves them without a separate build step.

After changing frontend code, run `npm run build` and commit the updated static assets.

## Type Checking

```bash
npx vue-tsc --noEmit
```

Runs in CI. Catches type errors across `.ts` and `.vue` files.
