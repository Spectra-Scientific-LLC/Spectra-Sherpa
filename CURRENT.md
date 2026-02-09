# CURRENT

This document tracks items not yet done but critical for the deployment of Local/Hybrid/Demo modes to Digital Ocean.

## 1. Server-Side Sherpa Agent (SpectraSherpa Server)
**Source**: `SHERPA_IMPLEMENTATION_PLAN.md`
**Status**: 🚧 PENDING (Essential for Hybrid/Demo Mode)

The client-side integration is done, but the server-side brain is missing. Without this, the "Hybrid" and "Demo" modes deployed to Digital Ocean will lack core AI capabilities.

- **Step 1: Create Skills Directory**: Must implement `spectrasherpa-server/skills/` with 9 domain `SKILL.md` files (Preprocessing, Modeling, etc.).
- **Step 2: Server Schemas**: Mirror `WorkflowStateSync`, `SherpaRecommendation` models on the server.
- **Step 3: LLM Provider Service**: Implement `LLMProvider` to query Anthropic/OpenAI using managed keys.
- **Step 4: Sherpa Agent Service**: Implement the logic to load skills, build prompts, and parse LLM responses.
- **Step 5: API Routes**: Implement `/api/v1/sherpa/sync`, `/decide`, and `/health` endpoints.
- **Step 6: Server Integration**: Wire up router and lifespan events in `main.py`.

## 2. Capability Gaps (Demo/Hybrid Stability)
**Source**: `docs/current/CAPABILITY_GAP_BACKLOG.md`
**Status**: 🚧 PENDING (Fixes needed for public demo reliability)

- **Priority 3: Rate-Limited Response Headers**: Ensure consistent `X-RateLimit-*` headers across all endpoints (not just LLM/NIST). Critical for Demo mode monitoring.
- **Priority 3: Feature Flag Consistency**: Centralize fallback semantics for `/config` to prevent frontend/backend drift. Important for toggling features in Demo vs Hybrid.

## 3. Deployment Configuration
**Source**: `docs/deployment/DIGITAL_OCEAN.md`
**Status**: 🚧 PENDING (Requires Server Component)

- **Docker Image**: Need to build and push the `spectrasherpa-server` image once the code (Item 1) is implemented.
- **Environment Setup**: Production configuration of `SPECTRASHERPA_SERVER_URL` and keys in DO environment.
