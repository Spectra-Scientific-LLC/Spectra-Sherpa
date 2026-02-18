<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useAppConfig } from '@/composables/useAppConfig'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Password from 'primevue/password'
import Card from 'primevue/card'

const authStore = useAuthStore()
const { registrationRequiresCode } = useAppConfig()

const username = ref('')
const email = ref('')
const password = ref('')
const confirmPassword = ref('')
const accessCode = ref('')
const loading = ref(false)
const validationError = ref<string | null>(null)

const requiresAccessCode = () => registrationRequiresCode.value

const handleRegister = async () => {
  validationError.value = null
  authStore.registerError = null

  if (!username.value || !password.value || !confirmPassword.value) {
    validationError.value = 'Username and password fields are required'
    return
  }
  if (email.value && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value)) {
    validationError.value = 'Please enter a valid email address'
    return
  }
  if (requiresAccessCode() && !accessCode.value) {
    validationError.value = 'Access code is required'
    return
  }
  if (username.value.length < 3) {
    validationError.value = 'Username must be at least 3 characters'
    return
  }
  if (password.value.length < 8) {
    validationError.value = 'Password must be at least 8 characters'
    return
  }
  if (password.value !== confirmPassword.value) {
    validationError.value = 'Passwords do not match'
    return
  }

  loading.value = true
  await authStore.register(username.value, password.value, accessCode.value, email.value || undefined)
  loading.value = false
}
</script>

<template>
  <div class="flex align-items-center justify-content-center min-h-screen surface-ground">
    <Card class="w-full md:w-30rem">
      <template #title>
        <div class="text-center mb-4">
          <h2 class="text-900 font-bold mb-2">Create Account</h2>
          <p class="text-600 font-medium">Register for Spectra Scientific</p>
        </div>
      </template>

      <template #content>
        <form @submit.prevent="handleRegister" class="flex flex-column" style="gap: 1.75rem">
          <div class="flex flex-column gap-2">
            <label for="username" class="font-bold text-900">Username</label>
            <InputText id="username" v-model="username" placeholder="Choose a username" class="w-full" />
          </div>

          <div class="flex flex-column gap-2">
            <label for="email" class="font-bold text-900">Email <span class="text-500 font-normal">(optional)</span></label>
            <InputText id="email" v-model="email" type="email" placeholder="For maintenance notifications" class="w-full" />
          </div>

          <div class="flex flex-column gap-2">
            <label for="password" class="font-bold text-900">Password</label>
            <Password
                id="password"
                v-model="password"
                :feedback="true"
                toggleMask
                placeholder="Choose a password (min 8 characters)"
                inputClass="w-full"
                class="w-full"
            />
          </div>

          <div class="flex flex-column gap-2">
            <label for="confirmPassword" class="font-bold text-900">Confirm Password</label>
            <Password
                id="confirmPassword"
                v-model="confirmPassword"
                :feedback="false"
                toggleMask
                placeholder="Confirm your password"
                inputClass="w-full"
                class="w-full"
            />
          </div>

          <div v-if="registrationRequiresCode" class="flex flex-column gap-2">
            <label for="accessCode" class="font-bold text-900">Access Code</label>
            <InputText id="accessCode" v-model="accessCode" type="password" placeholder="Enter the access code" class="w-full" />
          </div>

          <div v-if="validationError" class="text-red-500 text-sm">
            {{ validationError }}
          </div>

          <div v-if="authStore.registerError" class="text-red-500 text-sm">
            {{ authStore.registerError }}
          </div>

          <div v-if="authStore.registerSuccess" class="text-green-500 text-sm">
            {{ authStore.registerSuccess }}
          </div>

          <Button label="Create Account" type="submit" :loading="loading" class="w-full mt-4" />

          <div class="text-center mt-5">
            <span class="text-600">Already have an account? </span>
            <router-link to="/login" class="font-medium no-underline text-blue-500 cursor-pointer">Sign In</router-link>
          </div>
        </form>
      </template>
    </Card>
  </div>
</template>
