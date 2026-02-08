<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Password from 'primevue/password'
import Card from 'primevue/card'

const authStore = useAuthStore()

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
        <form @submit.prevent="handleLogin" class="flex flex-column gap-3">
          <div class="flex flex-column gap-2">
            <label for="username" class="font-bold text-900">Username</label>
            <InputText id="username" v-model="username" placeholder="Enter your username" class="w-full" />
          </div>

          <div class="flex flex-column gap-2">
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

          <div v-if="authStore.loginError" class="text-red-500 text-sm">
            {{ authStore.loginError }}
          </div>

          <Button label="Sign In" type="submit" :loading="loading" class="w-full mt-2" />
        </form>
      </template>
    </Card>
  </div>
</template>
