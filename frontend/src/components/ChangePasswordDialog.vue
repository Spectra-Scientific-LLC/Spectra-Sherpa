<script setup lang="ts">
import { ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import Dialog from 'primevue/dialog'
import Button from 'primevue/button'
import Password from 'primevue/password'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{ (e: 'update:visible', value: boolean): void }>()

const authStore = useAuthStore()

const currentPassword = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const loading = ref(false)
const error = ref<string | null>(null)
const success = ref<string | null>(null)

// Reset form when dialog opens
watch(() => props.visible, (val) => {
  if (val) {
    currentPassword.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    error.value = null
    success.value = null
  }
})

const handleSubmit = async () => {
  error.value = null
  success.value = null

  if (!currentPassword.value || !newPassword.value || !confirmPassword.value) {
    error.value = 'All fields are required'
    return
  }
  if (newPassword.value.length < 8) {
    error.value = 'New password must be at least 8 characters'
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    error.value = 'New passwords do not match'
    return
  }

  loading.value = true
  const result = await authStore.changePassword(currentPassword.value, newPassword.value)
  loading.value = false

  if (result.success) {
    success.value = 'Password changed successfully'
    setTimeout(() => emit('update:visible', false), 1500)
  } else {
    error.value = result.error || 'Password change failed'
  }
}
</script>

<template>
  <Dialog
    :visible="visible"
    @update:visible="emit('update:visible', $event)"
    header="Change Password"
    :modal="true"
    :style="{ width: '28rem' }"
  >
    <form @submit.prevent="handleSubmit" class="flex flex-column gap-4">
      <div class="flex flex-column gap-2">
        <label for="currentPassword" class="font-bold text-900">Current Password</label>
        <Password
          id="currentPassword"
          v-model="currentPassword"
          :feedback="false"
          toggleMask
          placeholder="Enter current password"
          inputClass="w-full"
          class="w-full"
        />
      </div>

      <div class="flex flex-column gap-2">
        <label for="newPassword" class="font-bold text-900">New Password</label>
        <Password
          id="newPassword"
          v-model="newPassword"
          :feedback="true"
          toggleMask
          placeholder="Enter new password (min 8 characters)"
          inputClass="w-full"
          class="w-full"
        />
      </div>

      <div class="flex flex-column gap-2">
        <label for="confirmNewPassword" class="font-bold text-900">Confirm New Password</label>
        <Password
          id="confirmNewPassword"
          v-model="confirmPassword"
          :feedback="false"
          toggleMask
          placeholder="Confirm new password"
          inputClass="w-full"
          class="w-full"
        />
      </div>

      <div v-if="error" class="text-red-500 text-sm">{{ error }}</div>
      <div v-if="success" class="text-green-500 text-sm">{{ success }}</div>

      <div class="flex justify-content-end gap-2 mt-2">
        <Button label="Cancel" class="p-button-text" @click="emit('update:visible', false)" />
        <Button label="Change Password" type="submit" :loading="loading" />
      </div>
    </form>
  </Dialog>
</template>
