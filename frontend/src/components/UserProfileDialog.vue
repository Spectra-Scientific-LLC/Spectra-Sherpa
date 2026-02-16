<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import Dialog from 'primevue/dialog'
import ProgressBar from 'primevue/progressbar'
import Tag from 'primevue/tag'
import InputText from 'primevue/inputtext'
import Button from 'primevue/button'
import api from '@/api/client'

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{ (e: 'update:visible', value: boolean): void }>()

interface UserProfile {
  user: {
    id: number
    username: string
    email: string | null
    is_superuser: boolean
    created_at: string | null
  }
  rateLimit?: {
    limit: number
    remaining: number
    used: number
    windowSeconds: number
  }
  session?: {
    expiresAt: string
    maxHours: number
  }
  projects: { count: number }
  executions: { total: number }
}

const profile = ref<UserProfile | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)

// Email editing
const editingEmail = ref(false)
const emailDraft = ref('')
const emailSaving = ref(false)
const emailMessage = ref<{ text: string; type: 'success' | 'error' } | null>(null)

const fetchProfile = async () => {
  loading.value = true
  error.value = null
  editingEmail.value = false
  emailMessage.value = null
  try {
    const response = await api.get('/auth/profile')
    profile.value = response.data
  } catch (err: any) {
    error.value = err.response?.data?.detail || 'Failed to load profile'
  } finally {
    loading.value = false
  }
}

const startEditEmail = () => {
  emailDraft.value = profile.value?.user.email || ''
  editingEmail.value = true
  emailMessage.value = null
}

const cancelEditEmail = () => {
  editingEmail.value = false
  emailMessage.value = null
}

const saveEmail = async () => {
  emailSaving.value = true
  emailMessage.value = null
  try {
    const emailValue = emailDraft.value.trim() || null
    await api.put('/auth/email', { email: emailValue })
    if (profile.value) {
      profile.value.user.email = emailValue
    }
    editingEmail.value = false
    emailMessage.value = { text: 'Email updated', type: 'success' }
    setTimeout(() => { emailMessage.value = null }, 2000)
  } catch (err: any) {
    emailMessage.value = { text: err.response?.data?.detail || 'Failed to update email', type: 'error' }
  } finally {
    emailSaving.value = false
  }
}

watch(() => props.visible, (val) => {
  if (val) fetchProfile()
})

const usagePercent = computed(() => {
  if (!profile.value?.rateLimit) return 0
  const { limit, used } = profile.value.rateLimit
  return Math.round((used / limit) * 100)
})

const usageSeverity = computed(() => {
  const pct = usagePercent.value
  if (pct >= 90) return 'danger'
  if (pct >= 70) return 'warning'
  return undefined
})

const sessionRemaining = computed(() => {
  if (!profile.value?.session?.expiresAt) return null
  const expires = new Date(profile.value.session.expiresAt)
  const now = new Date()
  const diffMs = expires.getTime() - now.getTime()
  if (diffMs <= 0) return 'Expired'
  const hours = Math.floor(diffMs / 3600000)
  const minutes = Math.floor((diffMs % 3600000) / 60000)
  if (hours > 0) return `${hours}h ${minutes}m`
  return `${minutes}m`
})

const memberSince = computed(() => {
  if (!profile.value?.user.created_at) return 'N/A'
  return new Date(profile.value.user.created_at).toLocaleDateString('en-US', {
    year: 'numeric', month: 'long', day: 'numeric'
  })
})
</script>

<template>
  <Dialog
    :visible="visible"
    @update:visible="emit('update:visible', $event)"
    header="User Profile"
    :modal="true"
    :style="{ width: '32rem' }"
  >
    <div v-if="loading" class="flex justify-content-center p-4">
      <i class="pi pi-spin pi-spinner" style="font-size: 2rem"></i>
    </div>

    <div v-else-if="error" class="text-red-500 p-3">{{ error }}</div>

    <div v-else-if="profile" class="flex flex-column gap-4">
      <!-- Account Info -->
      <div class="profile-section">
        <div class="profile-section-title">Account</div>
        <div class="profile-grid">
          <div class="profile-label">Username</div>
          <div class="profile-value">
            {{ profile.user.username }}
            <Tag v-if="profile.user.is_superuser" value="Admin" severity="info" class="ml-2" />
          </div>

          <div class="profile-label">Email</div>
          <div class="profile-value">
            <template v-if="editingEmail">
              <div class="flex align-items-center gap-2 w-full">
                <InputText
                  v-model="emailDraft"
                  placeholder="you@example.com"
                  class="flex-1"
                  size="small"
                  @keyup.enter="saveEmail"
                  @keyup.escape="cancelEditEmail"
                />
                <Button icon="pi pi-check" class="p-button-text p-button-sm p-button-success" :loading="emailSaving" @click="saveEmail" />
                <Button icon="pi pi-times" class="p-button-text p-button-sm" @click="cancelEditEmail" />
              </div>
            </template>
            <template v-else>
              <span :class="{ 'text-400': !profile.user.email }">
                {{ profile.user.email || 'Not set' }}
              </span>
              <Button icon="pi pi-pencil" class="p-button-text p-button-sm p-button-rounded ml-2" @click="startEditEmail" />
            </template>
          </div>

          <template v-if="emailMessage">
            <div></div>
            <div :class="emailMessage.type === 'success' ? 'text-green-500' : 'text-red-500'" class="text-xs">
              {{ emailMessage.text }}
            </div>
          </template>

          <div class="profile-label">Member since</div>
          <div class="profile-value">{{ memberSince }}</div>

          <div class="profile-label">Projects</div>
          <div class="profile-value">{{ profile.projects.count }}</div>

          <div class="profile-label">Total executions</div>
          <div class="profile-value">{{ profile.executions.total }}</div>
        </div>
      </div>

      <!-- Rate Limit Usage -->
      <div v-if="profile.rateLimit" class="profile-section">
        <div class="profile-section-title">Usage (hourly)</div>
        <div class="flex flex-column gap-2">
          <div class="flex justify-content-between text-sm">
            <span>{{ profile.rateLimit.used }} / {{ profile.rateLimit.limit }} executions</span>
            <span>{{ profile.rateLimit.remaining }} remaining</span>
          </div>
          <ProgressBar
            :value="usagePercent"
            :showValue="false"
            style="height: 8px"
            :class="{ 'usage-warning': usageSeverity === 'warning', 'usage-danger': usageSeverity === 'danger' }"
          />
          <div class="text-xs text-500">Resets every hour (sliding window)</div>
        </div>
      </div>

      <!-- Session Info -->
      <div v-if="profile.session" class="profile-section">
        <div class="profile-section-title">Session</div>
        <div class="profile-grid">
          <div class="profile-label">Time remaining</div>
          <div class="profile-value">
            <Tag
              :value="sessionRemaining || ''"
              :severity="sessionRemaining === 'Expired' ? 'danger' : 'success'"
            />
          </div>
          <div class="profile-label">Max session</div>
          <div class="profile-value">{{ profile.session.maxHours }} hours</div>
        </div>
      </div>
    </div>
  </Dialog>
</template>

<style scoped>
.profile-section {
  padding: 1rem;
  background: var(--surface-50, #f8fafc);
  border-radius: 8px;
  border: 1px solid var(--surface-200, #e2e8f0);
}

.profile-section-title {
  font-weight: 600;
  font-size: 0.875rem;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-color-secondary, #64748b);
  margin-bottom: 0.75rem;
}

.profile-grid {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.5rem 1rem;
  align-items: center;
}

.profile-label {
  font-size: 0.875rem;
  color: var(--text-color-secondary, #64748b);
}

.profile-value {
  font-size: 0.875rem;
  font-weight: 500;
  display: flex;
  align-items: center;
}

:deep(.usage-warning .p-progressbar-value) {
  background: var(--yellow-500, #eab308);
}

:deep(.usage-danger .p-progressbar-value) {
  background: var(--red-500, #ef4444);
}
</style>
