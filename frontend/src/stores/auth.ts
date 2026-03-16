/* eslint-disable @typescript-eslint/no-explicit-any -- auth error payloads come from heterogeneous backend/axios shapes. */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import api from '@/api/client'
import router from '@/router'

interface User {
    id: number
    username: string
    is_superuser: boolean
}

export const useAuthStore = defineStore('auth', () => {
    const token = ref<string | null>(localStorage.getItem('token'))
    const user = ref<User | null>(null)
    const isAuthenticated = computed(() => !!token.value || !!user.value)
    const loginError = ref<string | null>(null)
    const registerError = ref<string | null>(null)
    const registerSuccess = ref<string | null>(null)

    async function login(username: string, password: string) {
        try {
            loginError.value = null
            const formData = new FormData()
            formData.append('username', username)
            formData.append('password', password)

            const response = await api.post('/auth/login', formData)
            token.value = response.data.access_token
            if (token.value) {
                localStorage.setItem('token', token.value)
                await fetchUser()
                router.push('/')
            }
        } catch (error: any) {
            console.error('Login failed', error)
            loginError.value = error.response?.data?.detail || 'Login failed'
        }
    }

    async function register(username: string, password: string, enterprisePassword: string, email?: string) {
        try {
            registerError.value = null
            registerSuccess.value = null
            const body: Record<string, string> = { username, password }
            if (email) body.email = email
            await api.post('/auth/register', body, {
                headers: { 'X-Enterprise-Password': enterprisePassword }
            })
            registerSuccess.value = 'Account created successfully. You can now sign in.'
            router.push('/login')
        } catch (error: any) {
            registerError.value = error.response?.data?.detail || 'Registration failed'
        }
    }

    async function fetchUser() {
        if (!token.value) return
        try {
            const response = await api.get('/auth/me')
            user.value = response.data
        } catch (error) {
            console.error('Fetch user failed', error)
            // Only logout if token is still present. If clearCredentials()
            // ran while this request was in flight (e.g. mode switched to
            // local/hybrid), the token is already null — don't clobber state.
            if (token.value) {
                logout()
            }
        }
    }

    /**
     * Clear stale auth artifacts without navigating to /login.
     * Used when switching to a mode that doesn't need JWT (e.g. hybrid).
     */
    function clearCredentials() {
        token.value = null
        localStorage.removeItem('token')
        localStorage.removeItem('api_key')
    }

    async function initHybridUser() {
        // Hybrid mode uses implicit loopback identity, not JWT.
        // Clear stale tokens from prior enterprise usage to prevent WS 1008.
        if (token.value || localStorage.getItem('token') || localStorage.getItem('api_key')) {
            clearCredentials()
        }
        try {
            const response = await api.get('/auth/me')
            user.value = response.data
        } catch {
            console.warn('Could not fetch hybrid user profile')
        }
    }

    async function changePassword(currentPassword: string, newPassword: string): Promise<{ success: boolean; error?: string }> {
        try {
            await api.put('/auth/password', {
                current_password: currentPassword,
                new_password: newPassword,
            })
            return { success: true }
        } catch (error: any) {
            return { success: false, error: error.response?.data?.detail || 'Password change failed' }
        }
    }

    function logout() {
        token.value = null
        user.value = null
        localStorage.removeItem('token')
        router.push('/login')
    }

    // Restore session if token exists (interceptor adds header automatically)
    if (token.value) {
        fetchUser()
    }

    return {
        token,
        user,
        isAuthenticated,
        loginError,
        registerError,
        registerSuccess,
        login,
        register,
        changePassword,
        logout,
        clearCredentials,
        fetchUser,
        initHybridUser
    }
})
