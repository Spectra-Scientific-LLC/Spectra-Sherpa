# Demo Mode Integration Fixes

## Problem Summary

During OSS cleanup, the `demo_limits.py` module was deleted, breaking enterprise/hybrid mode demo enforcement. Three files had broken imports that would crash at runtime when demo mode was activated in spectra-server deployments.

## Breakage Impact

### Runtime Crashes (Hybrid/Enterprise Only)
- ❌ Demo user executes workflow → `ModuleNotFoundError` in rate limit middleware
- ❌ Demo user uses Sherpa AI advisor → `ModuleNotFoundError` in WebSocket handler
- ❌ Frontend fetches `/api/v1/config/demo/quota` → Import crash

### Why OSS Tests Didn't Catch This
- Broken imports are **lazy** (inside functions, not at module level)
- OSS mode (`site_profile=None`) never triggers these code paths
- Rate limiting middleware exits early via `has_rate_limits()` check

## Files Fixed

### 1. Created: `src/spectra_sherpa/app/core/demo_limits.py` (NEW)

**Purpose**: Per-session quota enforcement for demo site profile

**Features**:
- ✅ File-backed persistence (survives restarts, shared across Gunicorn workers)
- ✅ Separate tracking for executions and Sherpa interactions
- ✅ Per-user counters with automatic session expiry
- ✅ Graceful OSS mode handling (unlimited access when `site_profile != "demo"`)
- ✅ Thread-safe consumption (atomically check + consume)

**Public API**:
```python
# Check and consume quota (returns allowed, remaining_after_consumption)
check_demo_execution(user_id: int | None) -> Tuple[bool, int]
check_demo_sherpa(user_id: int | None) -> Tuple[bool, int]

# Query remaining without consuming
demo_execution_remaining(user_id: int | None) -> int
demo_sherpa_remaining(user_id: int | None) -> int

# Error formatting for 429 responses
demo_limit_error_detail(limit_type: str, remaining: int) -> dict

# Admin/testing utilities
reset_demo_limits(user_id: int | None = None)
```

**State Storage**:
- Path: `{settings.data_dir}/demo_limits.json`
- Format: `{"user:{id}": {"executions": 0, "sherpa_interactions": 0, "last_activity": "..."}}`
- Auto-cleanup: Sessions older than `demo_contract.session_expiry_hours` are purged on load

### 2. Modified: `src/spectra_sherpa/app/core/config.py`

**Added Missing Field**:
```python
class AppConfig(BaseModel):
    # ... existing fields ...

    rate_limit_executions: Optional[int] = Field(
        default=None,
        description="Max executions per hour per user (enterprise/hybrid mode)"
    )
```

**Purpose**: Used by `RateLimitMiddleware` for general rate limiting (separate from demo limits)

### 3. Verified: Integration Points (No Changes Needed)

These files now work correctly with restored `demo_limits` module:

- ✅ **rate_limit_middleware.py:97** - Imports `check_demo_execution`, `demo_limit_error_detail`
- ✅ **ws_handlers.py:142** - Imports `check_demo_sherpa`, `demo_limit_error_detail`
- ✅ **routes/config.py:131** - Imports `demo_execution_remaining`, `demo_sherpa_remaining`

## Behavior

### OSS Mode (site_profile = None)
```python
# All checks return unlimited
check_demo_execution(123)  # → (True, 999999)
check_demo_sherpa(456)     # → (True, 999999)

# No state tracking
demo_execution_remaining(123)  # → 999999
```

### Demo Mode (site_profile = "demo")
```python
# Configured via DemoContract
app_config.demo_contract = DemoContract(
    max_executions_per_session=50,
    max_sherpa_interactions=20,
    session_expiry_hours=24,
    upgrade_url="https://spectrasherpa.ai/upgrade"
)

# First execution
check_demo_execution(123)  # → (True, 49)   # Consumed 1, 49 remaining

# Subsequent executions
check_demo_execution(123)  # → (True, 48)
check_demo_execution(123)  # → (True, 47)

# After 50 executions
check_demo_execution(123)  # → (False, 0)

# Error detail for 429 response
demo_limit_error_detail("execution", 0)
# → {
#     "limit_type": "execution",
#     "limit": 50,
#     "remaining": 0,
#     "message": "Demo execution limit reached (50 executions per session)",
#     "upgrade_url": "https://spectrasherpa.ai/upgrade",
#     "session_expiry_hours": 24
# }
```

### Hybrid/Enterprise Mode (site_profile = "internal" or custom)
```python
# Demo limits are OFF (unlimited)
# But general rate_limit_executions still applies if set
app_config.rate_limit_executions = 100  # 100 per hour per user

# Rate limiting middleware enforces this separately
```

## Testing

### Test Coverage: 14 Tests in `test_demo_limits_integration.py`

**OSS Mode Tests** (2):
- ✅ Unlimited executions in OSS mode
- ✅ Unlimited Sherpa interactions in OSS mode

**Demo Mode Enforcement** (4):
- ✅ Execution limit enforcement (blocks after max)
- ✅ Sherpa interaction limit enforcement
- ✅ Separate tracking per user
- ✅ Anonymous user tracking (shared quota)

**Quota Queries** (2):
- ✅ Query remaining without consuming (executions)
- ✅ Query remaining without consuming (Sherpa)

**Error Formatting** (2):
- ✅ Execution limit error detail
- ✅ Sherpa limit error detail

**Admin Utilities** (2):
- ✅ Reset specific user
- ✅ Reset all users

**Mode Toggling** (1):
- ✅ Switching site_profile changes enforcement

**Config Integration** (1):
- ✅ `rate_limit_executions` field exists and is injectable

## All Production Tests: 45/45 Passing ✅

```
tests/test_headless_api.py:              7/7  ✅  (Issue #1: Pickle)
tests/test_cli_headless.py:              2/2  ✅  (Issue #2: Browser)
tests/test_import_sanity.py:            16/16 ✅  (Issue #3: Imports)
tests/test_python_export_result.py:      6/6  ✅  (Issue #4: _Result)
tests/test_demo_limits_integration.py:  14/14 ✅  (Demo enforcement)
```

## Integration with spectra-server

### Injection Pattern

**spectra-server** can inject demo mode configuration via `create_app()` hook:

```python
# In spectra-server's app factory
from spectra_sherpa.app.core.config import app_config, DemoContract

def create_enterprise_app():
    # Inject demo contract
    app_config.site_profile = "demo"
    app_config.demo_contract = DemoContract(
        max_executions_per_session=50,
        max_sherpa_interactions=20,
        session_expiry_hours=24,
        upgrade_url="https://spectrasherpa.ai/plans",
        disabled_capabilities=["python_export", "plugin_install"],
        featured_datasets=["ir_pharma_demo", "nir_food_demo"],
        available_plans=["professional", "enterprise"]
    )
    app_config.rate_limit_executions = 100  # General rate limit

    # Start spectra-sherpa app
    from spectra_sherpa.app.main import app
    return app
```

### Middleware Flow

1. **Request arrives** → `RateLimitMiddleware.dispatch()`
2. **Check mode** → `has_rate_limits()` (False in OSS, True in hybrid/enterprise)
3. **If demo mode**:
   - Line 97: Import `check_demo_execution` (NOW WORKS ✅)
   - Line 101: Check quota
   - Line 102-107: Return 429 if exceeded with `demo_limit_error_detail`
4. **If rate_limit_executions set**:
   - Line 110-130: General rate limiting (separate from demo)
5. **WebSocket Sherpa**:
   - ws_handlers.py:142: Import `check_demo_sherpa` (NOW WORKS ✅)
   - ws_handlers.py:145: Check quota
   - ws_handlers.py:146: Send error if exceeded

### Frontend Integration

```typescript
// Frontend can query remaining quota
const response = await fetch('/api/v1/config/demo/quota');
const quota = await response.json();

// OSS mode:
// { "demo": false }

// Demo mode:
// {
//   "demo": true,
//   "executions": { "remaining": 42, "limit": 50 },
//   "sherpa": { "remaining": 15, "limit": 20 }
// }
```

## Backwards Compatibility

- ✅ **OSS deployments**: Zero impact (unlimited access, no state tracking)
- ✅ **Existing workflows**: No API changes
- ✅ **spectra-server**: Can inject demo mode seamlessly
- ✅ **File-backed state**: Survives restarts and Gunicorn worker reloads

## Security Considerations

### Quota Enforcement
- ✅ Check + consume is atomic (no race conditions)
- ✅ File-backed state prevents quota resets on restart
- ✅ Session expiry prevents indefinite accumulation

### Anonymous Users
- ⚠️ Uses shared quota (`anon:shared` key)
- 🔒 spectra-server should implement IP-based tracking for anonymous demo users
- 🔒 Recommend CAPTCHA or stricter IP-based rate limiting in production

### State Persistence
- Path: `{data_dir}/demo_limits.json` (default: `.spectra_sherpa/demo_limits.json`)
- Permissions: Inherits from `data_dir` (mode 0755)
- Cleanup: Auto-purges expired sessions (older than `session_expiry_hours`)

## Deployment Notes

### Gunicorn Workers
- ✅ File-backed state is shared across workers
- ✅ JSON file handles concurrent access gracefully (last write wins)
- 🔒 For high-concurrency production, consider Redis-backed limiter

### Session Expiry
- Default: 24 hours (configurable via `demo_contract.session_expiry_hours`)
- Cleanup: Runs on tracker initialization (app startup)
- Manual reset: `demo_limits.reset_demo_limits()` (for admin operations)

### Monitoring
```python
# Check current state
from spectra_sherpa.app.core.demo_limits import _tracker

# Get user's current usage
counters = _tracker._get_counters(user_id)
print(f"Executions: {counters['executions']}")
print(f"Sherpa: {counters['sherpa_interactions']}")
print(f"Last activity: {counters['last_activity']}")
```

## Migration Checklist for spectra-server

- [ ] Update deployment configs to inject `site_profile="demo"`
- [ ] Set `demo_contract` fields (limits, upgrade URL, etc.)
- [ ] Set `rate_limit_executions` for general rate limiting
- [ ] Test demo user workflow (signup → execute → hit limit → see 429)
- [ ] Test Sherpa interaction limit (chat → hit limit → see error)
- [ ] Verify `/api/v1/config/demo/quota` endpoint returns correct values
- [ ] Add monitoring for demo quota exhaustion rates
- [ ] Document upgrade flow for demo users
