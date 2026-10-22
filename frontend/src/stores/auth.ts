import { resetScientificQueryGuidance } from "@/lib/scientificQueryGuidance";
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
import { computed, ref, watch, onScopeDispose } from 'vue'
import { defineStore } from 'pinia'

import api from '@/api/client'
import { clearStoredApiKey } from '@/utils/authStorage'
import { useScopedRequest } from '@/composables/useScopedRequest'
import { readBrowserSession, sameBrowserSession, renewBrowserSession, endBrowserSession, SESSION_STORAGE_KEY } from '@/extension-contract/session-v1'

/** Per-user capability flags populated by the server's /auth/me response. */
interface UserCapabilities {
    admin?: boolean
}

interface User {
    id: number
    username: string
    principalKind?: 'human' | 'service' | string
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
    let storedSession = readBrowserSession()
    const token = ref<string | null>(storedSession.token)
    const user = ref<User | null>(null)
    // A credential rotates; a scientific workspace belongs to a login session.
    // Unclassified replacements remain boundaries, even for the same account.
    const sessionRevision = ref(0)
    let acceptingRenewal = false
    watch(token, () => {
        if (!acceptingRenewal) sessionRevision.value += 1
    }, { flush: 'sync' })
    watch(() => user.value?.id, () => { sessionRevision.value += 1 }, { flush: 'sync' })

    function captureSession() {
        return { token: token.value, userId: user.value?.id, revision: sessionRevision.value,
            browserSession: readBrowserSession() }
    }

    /** Only the acknowledged refresh of this still-current login rotates in place. */
    async function acceptRenewal(expected: ReturnType<typeof captureSession>, renewed: string): Promise<boolean> {
        const current = () => !!renewed && !!expected.token && expected.userId != null &&
            token.value === expected.token && user.value?.id === expected.userId &&
            sessionRevision.value === expected.revision
        if (!current() || expected.browserSession.token !== expected.token) return false
        const committed = await renewBrowserSession(expected.browserSession, renewed, current)
        if (!committed || !current()) return false
        acceptingRenewal = true
        try { storedSession = committed; token.value = renewed }
        finally { acceptingRenewal = false }
        return true
    }

    let checking: Promise<void> | null = null
    let checkingKey: string | null = null
    /** Receiving tabs verify the exact renewed credential before protected work. */
    async function ensureStoredSession(): Promise<void> {
        const incoming = readBrowserSession()
        if (sameBrowserSession(storedSession, incoming) || acceptingRenewal) return
        const expected = captureSession()
        const key = JSON.stringify(incoming)
        if (checkingKey === key && checking) return checking
        const isRenewal = incoming.transition === 'renew' && incoming.token &&
            incoming.loginId === storedSession.loginId &&
            incoming.generation > storedSession.generation && expected.userId != null
        if (!isRenewal) {
            storedSession = incoming
            sessionRevision.value += 1 // catches same-token explicit re-login
            token.value = incoming.token
            user.value = null
            throw new Error('Login session changed. Retry from the current account.')
        }
        checkingKey = key
        const pending = (async () => {
            try {
                // Raw fetch pins this exact credential and avoids the ordinary
                // client's expiry side effects and recursive session gate.
                const response = await fetch('/api/v1/auth/me', {
                    headers: { Authorization: `Bearer ${incoming.token}` },
                    signal: AbortSignal.timeout(10000),
                })
                if (!response.ok && response.status !== 401 && response.status !== 403) {
                    throw new Error('Session validation temporarily unavailable')
                }
                const identity = response.ok ? await response.json() : null
                if (!sameBrowserSession(incoming) || sessionRevision.value !== expected.revision ||
                    user.value?.id !== expected.userId) return
                if (!identity || identity.id !== expected.userId || identity.is_active === false) {
                    storedSession = incoming
                    sessionRevision.value += 1
                    token.value = incoming.token
                    user.value = null
                    throw new Error('Renewed credential rejected')
                }
                acceptingRenewal = true
                try { storedSession = incoming; token.value = incoming.token }
                finally { acceptingRenewal = false }
            } catch {
                // No identity proof: keep the display, refuse new protected work,
                // and allow a later request to retry validation.
                throw new Error('Session renewal could not be verified. Retry when connected.')
            } finally {
                if (checkingKey === key) { checking = null; checkingKey = null }
            }
        })()
        checking = pending.then(async () => {
            if (!sameBrowserSession(storedSession)) await ensureStoredSession()
        })
        return checking
    }
    const onStoredCredential = (event: Event) => {
        if (event instanceof StorageEvent && event.key !== SESSION_STORAGE_KEY &&
            event.key !== 'token' && event.key !== null) return
        void ensureStoredSession().catch(() => undefined)
    }
    window.addEventListener('storage', onStoredCredential)
    window.addEventListener('sherpa-session-changed', onStoredCredential)
    onScopeDispose(() => {
        window.removeEventListener('storage', onStoredCredential)
        window.removeEventListener('sherpa-session-changed', onStoredCredential)
    })
    const actorRequest = useScopedRequest(() => [token.value, user.value?.id])
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
     * loopback product) and by the server auth module's logout flow.
     */
    function clearCredentials() {
        const expected = readBrowserSession()
        // Explicit invalidation matters even when already logged out: an
        // in-flight implicit local actor lookup must not log the user back in.
        actorRequest.invalidate()
        if (token.value === null && user.value === null) sessionRevision.value += 1
        resetScientificQueryGuidance();
        token.value = null
        user.value = null
        clearStoredApiKey()
        return endBrowserSession(expected)
    }

    /**
     * Product bootstrap — resolve implicit loopback identity via the
     * OSS-compat `/auth/me`. The backend validates any retained credentials;
     * remote callers must not lose the API key needed to authenticate.
     */
    async function initializeActor() {
        const request = actorRequest.begin()
        try {
            const response = await api.get('/auth/me', { signal: request.signal })
            if (request.isCurrent()) user.value = response.data
        } catch {
            if (request.isCurrent()) console.warn('Could not fetch product user profile')
        }
    }

    return {
        token,
        user,
        sessionRevision: computed(() => sessionRevision.value),
        captureSession,
        acceptRenewal,
        ensureStoredSession,
        isAuthenticated,
        clearCredentials,
        initializeActor,
    }
})
