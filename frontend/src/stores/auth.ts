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
    const isAuthenticated = computed(() => !!token.value)
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
            logout()
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
        fetchUser
    }
})
