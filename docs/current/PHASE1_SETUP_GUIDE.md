# Phase 1 Setup Guide: Multi-Mode Configuration & LLM Integration

This guide walks through setting up the newly implemented configuration system for local, hybrid, and enterprise modes.

## What Was Built

### Backend
1. **Multi-mode configuration system** ([app/core/config.py](../../src/spectra_sherpa/app/core/config.py))
   - Support for `local`, `hybrid`, `enterprise` modes
   - LLM provider configuration (OpenAI, Anthropic, DeepSeek, Gemini)
   - Environment variable loading
   - Client-safe config endpoint

2. **Configuration API** ([app/api/v1/routes/config.py](../../src/spectra_sherpa/app/api/v1/routes/config.py))
   - `GET /api/v1/config` - Returns app mode, features, LLM status
   - `GET /api/v1/config/mode` - Current mode
   - `GET /api/v1/config/llms` - Configured providers

### Frontend
1. **Config types** ([frontend/src/types/config.ts](frontend/src/types/config.ts))
2. **Config composable** ([frontend/src/composables/useAppConfig.ts](frontend/src/composables/useAppConfig.ts))
3. **Token storage utilities** ([frontend/src/utils/tokenStorage.ts](frontend/src/utils/tokenStorage.ts))
4. **API Token Settings UI** ([frontend/src/components/settings/ApiTokenSettings.vue](frontend/src/components/settings/ApiTokenSettings.vue))

---

## Quick Start: Local Mode

### 1. Backend Setup

```bash
cd Refactored

# Copy environment template
cp .env.example .env

# Edit .env and add API keys for LLMs you want to use
nano .env
```

Add your API keys (example):
```bash
APP_MODE=local

# Add whichever LLM providers you want
OPENAI_API_KEY=sk-...
DEEPSEEK_API_KEY=sk-...
# Leave others blank if not using
```

### 2. Test Configuration Endpoint

Start the backend:
```bash
# From repo root (after pip install -e .)
spectra-sherpa
```

Test the config endpoint:
```bash
curl http://localhost:8000/api/v1/config | jq
```

Expected output:
```json
{
  "mode": "local",
  "api_base_url": "http://localhost:8000",
  "features": {
    "apiTokenSettings": true,
    "cloudOffload": false,
    "demoMode": false,
    "agenticWorkflow": true,  // if you have LLM configured
    "chatAssistant": false
  },
  "llms": {
    "openai": {
      "provider": "openai",
      "model": "gpt-4o",
      "enabled": true  // if OPENAI_API_KEY is set
    },
    // ... other providers
  },
  "limits": null  // only set in enterprise mode
}
```

### 3. Frontend Setup

The frontend will automatically load config from the backend on startup. The API token settings component is ready to use.

To add to your settings view:
```vue
<script setup>
import ApiTokenSettings from '@/components/settings/ApiTokenSettings.vue'
</script>

<template>
  <div class="settings-view">
    <ApiTokenSettings />
  </div>
</template>
```

---

## Adding Anthropic (Claude) Support

**Current state:** OpenAI, DeepSeek, Gemini work via `AsyncOpenAI` client
**Missing:** Anthropic uses a different SDK and API structure

### Step 1: Install Anthropic SDK

```bash
cd Refactored

# Add to requirements.txt
echo "anthropic>=0.39.0" >> requirements.txt

# Install
pip install anthropic
```

### Step 2: Update LLM Service

Edit [`app/services/llm.py`](../../src/spectra_sherpa/app/services/llm.py):

#### 2a. Add Anthropic Import
```python
# At the top of the file
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
```

#### 2b. Update `_resolve_api_key()` Method

Around line 198, add "anthropic" to the env_keys dict:
```python
async def _resolve_api_key(self, provider: str) -> str:
    # ...
    env_keys = {
        "deepseek": "DEEPSEEK_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",  # ADD THIS LINE
    }
    # ... rest of method
```

#### 2c. Update `_client()` Method

Replace the current `_client` method (around line 185-190) with:
```python
async def _client(self, config: dict[str, Any]) -> AsyncOpenAI | AsyncAnthropic:
    """Get LLM client based on provider"""
    api_key = await self._resolve_api_key(config["provider"])
    provider = config["provider"]

    import logging
    logger = logging.getLogger(__name__)
    logger.info(f"Creating client for provider={provider}, model={config['model']}")

    if provider == "anthropic":
        return AsyncAnthropic(api_key=api_key)
    else:
        # OpenAI-compatible providers (openai, deepseek, gemini)
        return AsyncOpenAI(api_key=api_key, base_url=config["base_url"])
```

#### 2d. Update `_single_turn()` Method

Replace around line 145-157:
```python
async def _single_turn(self, prompt: str) -> str:
    config = await self._get_llm_config()
    client = await self._client(config)

    if config["provider"] == "anthropic":
        # Anthropic API format
        response = await client.messages.create(
            model=config["model"],
            max_tokens=4096,
            messages=[
                {"role": "user", "content": prompt}
            ],
            system=DEFAULT_SYSTEM_PROMPT
        )
        return response.content[0].text
    else:
        # OpenAI-compatible format
        response = await client.chat.completions.create(
            model=config["model"],
            messages=[
                {"role": "system", "content": DEFAULT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            stream=False,
        )
        return response.choices[0].message.content or ""
```

#### 2e. Update `chat()` Method

Around line 64-84, update the chat method:
```python
async def chat(
    self,
    message: str,
    conversation_id: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> tuple[str, str]:
    conversation_id, history = conversation_store.get_or_create(conversation_id)
    history.append({"role": "user", "content": message})

    config = await self._get_llm_config()
    client = await self._client(config)
    payload = self._build_messages(history, metadata, config)

    if config["provider"] == "anthropic":
        # Anthropic format (extract system message)
        system_msg = payload[0]["content"] if payload[0]["role"] == "system" else DEFAULT_SYSTEM_PROMPT
        user_msgs = [m for m in payload if m["role"] != "system"]

        response = await client.messages.create(
            model=config["model"],
            max_tokens=4096,
            system=system_msg,
            messages=user_msgs
        )
        content = response.content[0].text
    else:
        # OpenAI format
        response = await client.chat.completions.create(
            model=config["model"],
            messages=payload,
            stream=False,
        )
        content = response.choices[0].message.content or ""

    history.append({"role": "assistant", "content": content})
    conversation_store.trim(conversation_id)
    return conversation_id, content
```

### Step 3: Add API Key

```bash
# In .env
ANTHROPIC_API_KEY=sk-ant-api03-...
ANTHROPIC_MODEL=claude-3-5-sonnet-20241022
```

### Step 4: Test

```bash
# Test config endpoint shows Anthropic as enabled
curl http://localhost:8000/api/v1/config | jq '.llms.anthropic'

# Test LLM chat
curl -X POST http://localhost:8000/api/v1/llm/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello, can you hear me?"}'
```

---

## Frontend: Using API Token Settings

### Option 1: Add to Existing Settings View

If you already have a settings view with tabs:

```vue
<!-- In SettingsView.vue or similar -->
<template>
  <TabView>
    <TabPanel header="Preferences">
      <PreferencesTab />
    </TabPanel>

    <TabPanel header="API Keys">
      <ApiTokenSettings />
    </TabPanel>

    <!-- Other tabs... -->
  </TabView>
</template>

<script setup>
import ApiTokenSettings from '@/components/settings/ApiTokenSettings.vue'
</script>
```

### Option 2: Standalone Route

Add a dedicated settings route in your router:

```typescript
// In router/index.ts
{
  path: '/settings',
  name: 'Settings',
  component: () => import('@/views/SettingsView.vue'),
  children: [
    {
      path: 'api-keys',
      component: () => import('@/components/settings/ApiTokenSettings.vue')
    }
  ]
}
```

### Usage Flow

1. **User opens settings** → Sees configured LLM providers
2. **Enters API key** → Click "Save" to store locally (browser storage)
3. **Sends to backend** → Click "Send to Backend" to configure server
4. **Tests connection** → Click "Test Connection" to verify

---

## Mode Switching

### Local Mode (Current Default)
```bash
# In .env
APP_MODE=local
```
- Single user on local machine
- Bring your own API tokens
- No rate limits

### Enterprise Mode (For Cloud Deployment)
```bash
# In .env
APP_MODE=enterprise
ENTERPRISE_PASSWORD=your-secure-password
RATE_LIMIT_EXECUTIONS=100
SESSION_EXPIRY_HOURS=24
```
- Single password for enterprise access
- Rate limited executions
- Ephemeral sessions

### Hybrid Mode (Future - GPU Offload)
```bash
# In .env
APP_MODE=hybrid
EXECUTION_MODE=hybrid
GRADIENT_API_KEY=your-gradient-key
AUTO_OFFLOAD_THRESHOLD=10000
```
- Local + cloud GPU for heavy computations
- Automatic offload when dataset > threshold
- Requires DigitalOcean Gradient AI account

---

## Troubleshooting

### Config Endpoint Returns 404
```bash
# Check if router is registered
grep "config.router" app/api/v1/api.py
```
Should see: `api_router.include_router(config.router, tags=["config"])`

### LLM Shows "Not Configured" Despite API Key
1. Check `.env` file has the key
2. Restart backend server
3. Check logs for config loading errors
4. Verify key format (should start with `sk-` for OpenAI/Anthropic)

### Frontend Can't Load Config
1. Check backend is running on correct port
2. Check CORS settings
3. Open browser console for network errors
4. Verify `/api/v1/config` endpoint works with curl

### Anthropic Chat Fails
- Check SDK is installed: `pip list | grep anthropic`
- Verify API key format
- Check model name matches Anthropic's naming
- Look for error in backend logs

---

## Next Steps (Phase 2+)

- **Demo deployment**: Deploy to DigitalOcean with authentication
- **Workflow generation**: Use configured LLMs to generate workflows from natural language
- **Chat assistant**: Interactive help for analyzing results
- **GPU offload**: Integrate Gradient AI for hybrid mode

---

## Configuration Reference

### Environment Variables

| Variable | Mode | Description | Default |
|----------|------|-------------|---------|
| `APP_MODE` | All | App mode: local, hybrid, enterprise | `local` |
| `OPENAI_API_KEY` | All | OpenAI API key | - |
| `ANTHROPIC_API_KEY` | All | Anthropic API key | - |
| `DEEPSEEK_API_KEY` | All | DeepSeek API key | - |
| `GEMINI_API_KEY` | All | Gemini API key | - |
| `EXECUTION_MODE` | Hybrid | Execution: local or hybrid | `local` |
| `GRADIENT_API_KEY` | Hybrid | DigitalOcean Gradient key | - |
| `ENTERPRISE_PASSWORD` | Enterprise | Enterprise access password | - |
| `RATE_LIMIT_EXECUTIONS` | Enterprise | Max executions per session | `100` |
| `SESSION_EXPIRY_HOURS` | Enterprise | Session lifetime | `24` |

---

## Support

For issues or questions:
1. Check this guide
2. Review `.env.example` for correct configuration
3. Check backend logs for detailed error messages
4. Test config endpoint: `curl http://localhost:8000/api/v1/config`
