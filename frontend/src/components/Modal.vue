<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import Icon from './Icon.vue'
defineProps({ title: String, wide: Boolean, closable: { type: Boolean, default: true } })
defineEmits(['close'])
const panel = ref(null)
let previousFocus
let previousOverflow
function keydown(event) {
  if (event.key !== 'Tab' || !panel.value) return
  const focusable = [
    ...panel.value.querySelectorAll(
      'button:not(:disabled), input:not(:disabled), a[href], select:not(:disabled), [tabindex="0"]',
    ),
  ].filter((el) => el.offsetParent !== null)
  const first = focusable[0]
  const last = focusable[focusable.length - 1]
  if (!first) {
    event.preventDefault()
    return
  }
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
  }
}
onMounted(async () => {
  previousFocus = document.activeElement
  previousOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
  await nextTick()
  const input =
    panel.value?.querySelector('[autofocus]') ||
    panel.value?.querySelector('input:not(:disabled), select:not(:disabled), button:not(:disabled)')
  input?.focus()
  document.addEventListener('keydown', keydown)
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', keydown)
  document.body.style.overflow = previousOverflow
  nextTick(() => previousFocus?.focus())
})
</script>

<template>
  <Teleport to="body">
    <div class="modal-backdrop" @mousedown.self="closable && $emit('close')">
      <section
        ref="panel"
        class="modal-panel"
        :class="{ wide }"
        role="dialog"
        aria-modal="true"
        :aria-label="title"
        @keydown.esc.stop="closable && $emit('close')"
      >
        <header class="modal-header">
          <h2>{{ title }}</h2>
          <button
            class="icon-button"
            :disabled="!closable"
            aria-label="Dialog schließen"
            @click="$emit('close')"
          >
            <Icon name="close" />
          </button>
        </header>
        <slot />
      </section>
    </div>
  </Teleport>
</template>
