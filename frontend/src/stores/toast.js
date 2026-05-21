import { ref } from 'vue'
import { defineStore } from 'pinia'

export const useToastStore = defineStore('toast', () => {
  const messages = ref([])
  let idCounter = 0

  function show(message, type = 'success') {
    const id = ++idCounter
    messages.value.push({ id, message, type })
    setTimeout(() => {
      remove(id)
    }, 3000)
  }

  function success(message) {
    show(message, 'success')
  }

  function error(message) {
    show(message, 'error')
  }

  function remove(id) {
    const idx = messages.value.findIndex(m => m.id === id)
    if (idx !== -1) {
      messages.value.splice(idx, 1)
    }
  }

  return { messages, show, success, error, remove }
})
