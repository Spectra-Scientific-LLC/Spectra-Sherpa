<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useAppConfig } from '@/composables/useAppConfig'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Password from 'primevue/password'
import Card from 'primevue/card'

const authStore = useAuthStore()
const { registrationEnabled } = useAppConfig()

const username = ref('')
const password = ref('')
const loading = ref(false)

const handleLogin = async () => {
  if (!username.value || !password.value) return
  
  loading.value = true
  await authStore.login(username.value, password.value)
  loading.value = false
}
</script>

<template>
  <div class="flex align-items-center justify-content-center min-h-screen surface-ground">
    <Card class="w-full md:w-30rem">
      <template #title>
        <div class="text-center mb-4">
          <h2 class="text-900 font-bold mb-2">Welcome Back</h2>
          <p class="text-600 font-medium">Sign in to Spectra Scientific</p>
        </div>
      </template>

      <template #content>
        <form @submit.prevent="handleLogin" class="auth-form">
          <div class="field-group">
            <label for="username" class="font-bold text-900">Username</label>
            <InputText id="username" v-model="username" placeholder="Enter your username" class="w-full" />
          </div>

          <div class="field-group">
            <label for="password" class="font-bold text-900">Password</label>
            <Password 
                id="password" 
                v-model="password" 
                :feedback="false" 
                toggleMask 
                placeholder="Enter your password" 
                inputClass="w-full"
                class="w-full"
            />
          </div>

          <div v-if="authStore.registerSuccess" class="text-green-500 text-sm">
            {{ authStore.registerSuccess }}
          </div>

          <div v-if="authStore.loginError" class="text-red-500 text-sm">
            {{ authStore.loginError }}
          </div>

          <Button label="Sign In" type="submit" :loading="loading" class="w-full mt-4" />

          <div v-if="registrationEnabled" class="text-center mt-5">
            <span class="text-600">Don't have an account? </span>
            <router-link to="/register" class="font-medium no-underline text-blue-500 cursor-pointer">Create Account</router-link>
          </div>
        </form>
      </template>
    </Card>
  </div>
</template>

<style scoped>
.auth-form {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
}

.field-group {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}
</style>
