<template>
  <div class="llm-chat-panel">
    <div class="chat-header">
      <div class="header-title">
        <i class="pi pi-comment"></i>
        <span>Workflow Assistant</span>
      </div>
      <Button
        icon="pi pi-times"
        class="p-button-text p-button-sm"
        @click="$emit('close')"
      />
    </div>

    <div class="chat-messages" ref="messagesContainer">
      <div v-for="(message, index) in messages" :key="index" class="message" :class="message.role">
        <div class="message-avatar">
          <i :class="message.role === 'user' ? 'pi pi-user' : 'pi pi-sparkles'"></i>
        </div>
        <div class="message-content">
          <div class="message-text">{{ message.content }}</div>
          <div class="message-time">{{ formatTime(message.timestamp) }}</div>
        </div>
      </div>

      <div v-if="isLoading" class="message assistant">
        <div class="message-avatar">
          <i class="pi pi-sparkles"></i>
        </div>
        <div class="message-content">
          <div class="typing-indicator">
            <span></span>
            <span></span>
            <span></span>
          </div>
        </div>
      </div>
    </div>

    <div class="chat-input">
      <Textarea
        v-model="currentMessage"
        placeholder="Ask about your workflow, request analysis, or get suggestions..."
        :autoResize="true"
        rows="2"
        @keydown.enter.exact.prevent="sendMessage"
      />
      <Button
        icon="pi pi-send"
        :disabled="!currentMessage.trim() || isLoading"
        @click="sendMessage"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, nextTick, watch } from 'vue'
import Button from 'primevue/button'
import Textarea from 'primevue/textarea'

interface Message {
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
}

interface Props {
  workflowContext?: {
    nodes: any[]
    edges: any[]
    selectedNode?: any
  }
}

const props = defineProps<Props>()
const emit = defineEmits<{
  (e: 'close'): void
}>()

const messages = ref<Message[]>([])
const currentMessage = ref('')
const isLoading = ref(false)
const messagesContainer = ref<HTMLElement | null>(null)

onMounted(() => {
  // Add welcome message
  messages.value.push({
    role: 'assistant',
    content: `Hello! I'm your Workflow Assistant. I can help you with:

• Analyzing your spectral data workflow
• Suggesting optimal processing steps
• Explaining node parameters and configurations
• Identifying peaks and patterns in your data
• Generating Python code for your workflow
• Troubleshooting errors or unexpected results

What would you like to know about your current workflow?`,
    timestamp: new Date(),
  })
})

const sendMessage = async () => {
  if (!currentMessage.value.trim() || isLoading.value) return

  // Add user message
  messages.value.push({
    role: 'user',
    content: currentMessage.value,
    timestamp: new Date(),
  })

  const userMessage = currentMessage.value
  currentMessage.value = ''
  isLoading.value = true

  await scrollToBottom()

  try {
    // TODO: Call actual LLM API with workflow context
    const response = await simulateLLMResponse(userMessage)

    messages.value.push({
      role: 'assistant',
      content: response,
      timestamp: new Date(),
    })
  } catch (error) {
    messages.value.push({
      role: 'assistant',
      content: 'Sorry, I encountered an error processing your request. Please try again.',
      timestamp: new Date(),
    })
  } finally {
    isLoading.value = false
    await scrollToBottom()
  }
}

const simulateLLMResponse = async (message: string): Promise<string> => {
  // Simulate API delay
  await new Promise(resolve => setTimeout(resolve, 1000))

  // Get workflow context
  const nodeCount = props.workflowContext?.nodes.length || 0
  const edgeCount = props.workflowContext?.edges.length || 0

  // Simple pattern matching for demo
  if (message.toLowerCase().includes('workflow')) {
    return `Your current workflow has ${nodeCount} node(s) and ${edgeCount} connection(s). ${
      nodeCount === 0
        ? "You haven't added any nodes yet. Try dragging preprocessing or analysis nodes from the left panel!"
        : 'You can connect nodes by dragging from the output handle (right side) of one node to the input handle (left side) of another.'
    }`
  }

  if (message.toLowerCase().includes('peak')) {
    return `For peak detection in spectral data, I recommend using the "Peak Detection" node. You can configure parameters like:
• Minimum peak height
• Minimum peak distance
• Signal-to-noise ratio threshold

Would you like me to explain how to configure these parameters?`
  }

  if (message.toLowerCase().includes('code') || message.toLowerCase().includes('python')) {
    return `I can generate Python code for your workflow! The exported code will include:
• Data loading and preprocessing steps
• Analysis pipeline matching your node configuration
• Result visualization and export

Click the "Export Python" button in the toolbar to generate the script.`
  }

  // Default response
  return `I understand you're asking about "${message}". Based on your current workflow with ${nodeCount} node(s), I can help you:

• Add preprocessing steps (baseline correction, smoothing, normalization)
• Configure analysis nodes (peak detection, curve fitting, classification)
• Optimize parameters for better results
• Export your workflow as Python code

What specific aspect would you like help with?`
}

const formatTime = (date: Date): string => {
  return date.toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

const scrollToBottom = async () => {
  await nextTick()
  if (messagesContainer.value) {
    messagesContainer.value.scrollTop = messagesContainer.value.scrollHeight
  }
}

// Auto-scroll on new messages
watch(() => messages.value.length, scrollToBottom)
</script>

<style scoped>
.llm-chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: #ffffff;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  overflow: hidden;
}

.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border-bottom: 1px solid #e2e8f0;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.header-title {
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 600;
  font-size: 1rem;
}

.header-title i {
  font-size: 1.2rem;
}

.chat-messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: #f8fafc;
}

.message {
  display: flex;
  gap: 12px;
  animation: fadeIn 0.3s ease-in;
}

@keyframes fadeIn {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.message-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.message.user .message-avatar {
  background: #3b82f6;
  color: white;
}

.message.assistant .message-avatar {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.message-content {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.message-text {
  padding: 12px 16px;
  border-radius: 12px;
  line-height: 1.5;
  white-space: pre-wrap;
}

.message.user .message-text {
  background: #3b82f6;
  color: white;
  margin-left: auto;
  max-width: 80%;
}

.message.assistant .message-text {
  background: #ffffff;
  color: #1e293b;
  border: 1px solid #e2e8f0;
  max-width: 90%;
}

.message-time {
  font-size: 0.75rem;
  color: #94a3b8;
  padding: 0 4px;
}

.message.user .message-time {
  text-align: right;
}

.typing-indicator {
  display: flex;
  gap: 4px;
  padding: 12px 16px;
  background: #ffffff;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  width: fit-content;
}

.typing-indicator span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #94a3b8;
  animation: typing 1.4s infinite;
}

.typing-indicator span:nth-child(2) {
  animation-delay: 0.2s;
}

.typing-indicator span:nth-child(3) {
  animation-delay: 0.4s;
}

@keyframes typing {
  0%, 60%, 100% {
    transform: translateY(0);
    opacity: 0.7;
  }
  30% {
    transform: translateY(-10px);
    opacity: 1;
  }
}

.chat-input {
  display: flex;
  gap: 8px;
  padding: 16px;
  border-top: 1px solid #e2e8f0;
  background: #ffffff;
}

.chat-input textarea {
  flex: 1;
}

.chat-input button {
  align-self: flex-end;
}
</style>
