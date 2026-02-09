import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import axios from 'axios'
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

    async function login(username: string, password: string) {
        try {
            loginError.value = null
            const formData = new FormData()
            formData.append('username', username)
            formData.append('password', password)

            const response = await axios.post('/api/v1/auth/login', formData)
            token.value = response.data.access_token
            if (token.value) {
                localStorage.setItem('token', token.value)
                axios.defaults.headers.common['Authorization'] = `Bearer ${token.value}`
                await fetchUser()
                router.push('/')
            }
        } catch (error: any) {
            console.error('Login failed', error)
            loginError.value = error.response?.data?.detail || 'Login failed'
        }
    }

    async function fetchUser() {
        if (!token.value) return
        try {
            const response = await axios.get('/api/v1/auth/me')
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
        delete axios.defaults.headers.common['Authorization']
    }

    async function initHybridUser() {
        // Hybrid mode uses implicit loopback identity, not JWT.
        // Clear stale tokens from prior demo usage to prevent WS 1008.
        if (token.value || localStorage.getItem('token') || localStorage.getItem('api_key')) {
            clearCredentials()
        }
        try {
            const response = await axios.get('/api/v1/auth/me')
            user.value = response.data
        } catch {
            console.warn('Could not fetch hybrid user profile')
        }
    }

    function logout() {
        token.value = null
        user.value = null
        localStorage.removeItem('token')
        delete axios.defaults.headers.common['Authorization']
        router.push('/login')
    }

    // Initialize axio headers if token exists
    if (token.value) {
        axios.defaults.headers.common['Authorization'] = `Bearer ${token.value}`
        fetchUser()
    }

    return {
        token,
        user,
        isAuthenticated,
        loginError,
        login,
        logout,
        clearCredentials,
        fetchUser,
        initHybridUser
    }
})
