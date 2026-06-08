/**
 * OSS auth store — identity-only.
 *
 * After v0.4.1 the managed-auth methods (login, register,
 * changePassword, fetchUser-with-token) live in the server-provided
 * frontend module (/ui/auth.js), not here. This store carries the
 * current-user ref + token + a couple of helpers that the OSS shell
 * and the server module both read. The server module writes user
 * identity back into this store after a successful /auth/me call so
 * the rest of the OSS app can see it.
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import api from '@/api/client'
import { clearStoredApiKey, hasStoredApiKey } from '@/utils/authStorage'

/** Per-user capability flags populated by the server's /auth/me response. */
interface UserCapabilities {
    admin?: boolean
}

interface User {
    id: number
    username: string
    is_active?: boolean
    /**
     * Per-user capability flags. Absent in local mode (OSS Actor
     * schema); populated by the server in managed-auth modes from
     * ManagedUserAccount state. Gate admin UI with
     * ``user?.capabilities?.admin``. The legacy ``is_superuser``
     * field is still on the wire for backward compat but is
     * intentionally not surfaced on this type — new code must use
     * capabilities.
     */
    capabilities?: UserCapabilities
}

export const useAuthStore = defineStore('auth', () => {
    const token = ref<string | null>(localStorage.getItem('token'))
    const user = ref<User | null>(null)
    // "Authenticated" requires a server-validated identity, not just the
    // presence of a token. A token alone may be stale or revoked; only
    // the user ref — populated by /auth/me — proves the credential was
    // accepted. Loose token-only semantics caused the v0.4.1 staging
    // boot bug where a stale JWT in localStorage let the router guard
    // pass through to /project, after which every API call 401'd.
    const isAuthenticated = computed(() => !!user.value)

    /**
     * Clear stale auth artifacts without navigating. Called when
     * switching to a mode that doesn't need JWT (e.g. local,
     * loopback hybrid) and by the server auth module's logout flow.
     */
    function clearCredentials() {
        token.value = null
        user.value = null
        localStorage.removeItem('token')
        clearStoredApiKey()
    }

    /**
     * Hybrid bootstrap — resolve implicit loopback identity via the
     * OSS-compat `/auth/me`. Clears any stale credentials first so
     * a prior enterprise session doesn't taint the hybrid handshake.
     */
    async function initHybridUser() {
        if (token.value || localStorage.getItem('token') || hasStoredApiKey()) {
            clearCredentials()
        }
        try {
            const response = await api.get('/auth/me')
            user.value = response.data
        } catch {
            console.warn('Could not fetch hybrid user profile')
        }
    }

    return {
        token,
        user,
        isAuthenticated,
        clearCredentials,
        initHybridUser,
    }
})
