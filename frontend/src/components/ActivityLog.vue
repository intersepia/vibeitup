<script setup>
import { computed } from 'vue'
import Icon from './Icon.vue'
const props = defineProps({ logs: Array, events: Array, expanded: Boolean, indexedAt: String })
defineEmits(['toggle', 'show-all'])
function label(transaction) {
  const count = transaction.files.length
  const noun = count === 1 ? 'Bild' : 'Bilder'
  if (transaction.status === 'undone') return `${count} ${noun} zurück im Eingang · Aktion rückgängig gemacht`
  if (transaction.status === 'interrupted')
    return `Aktion unterbrochen · ${transaction.error || 'Bitte Dateipfade im Protokoll prüfen'}`
  if (transaction.status === 'rolled_back')
    return `Aktion sicher zurückgesetzt · ${transaction.error || 'Wiederherstellung nach Neustart'}`
  if (transaction.action === 'trash') return `${count} ${noun} in den Papierkorb verschoben`
  if (transaction.action === 'duplicates') return `${count} ${noun} in Duplikate abgelegt`
  const target = transaction.files[0]?.destination.split('/').slice(1, -1).join('/')
  return `${count} ${noun} nach „${target}“ verschoben`
}
const rows = computed(() => {
  const items = props.logs.map((log) => ({
    id: log.id,
    date: log.undone_at || log.created_at,
    text: label(log),
    error: log.status === 'interrupted',
  }))
  items.push(...props.events)
  if (props.indexedAt)
    items.push({
      id: 'index',
      date: props.indexedAt,
      text: 'Bibliothek eingelesen. Alles bereit zum Sortieren.',
    })
  return items.sort((a, b) => new Date(b.date) - new Date(a.date)).slice(0, 3)
})
function time(value) {
  return new Date(value).toLocaleTimeString('de-DE', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}
</script>

<template>
  <section class="activity-log" :class="{ collapsed: !expanded }" aria-label="Letzte Aktivitäten">
    <div class="activity-header">
      <button :aria-expanded="expanded" @click="$emit('toggle')">
        <Icon name="terminal" :size="15" /><strong>Letzte Aktivitäten</strong
        ><span class="activity-live-dot"></span
        ><Icon :name="expanded ? 'down' : 'chevron'" :size="13" /></button
      ><button class="activity-show-all" @click="$emit('show-all')">
        Protokoll öffnen <Icon name="arrow" :size="12" />
      </button>
    </div>
    <div v-if="expanded" class="activity-rows" aria-live="polite">
      <div v-for="row in rows" :key="row.id" class="activity-row" :class="{ 'log-error': row.error }">
        <time>{{ time(row.date) }}</time
        ><Icon :name="row.error ? 'warning' : 'check'" :size="12" /><span>{{ row.text }}</span>
      </div>
      <div v-if="!rows.length" class="activity-row">
        <time>––:––:––</time><span>Deine nächste gute Sortierentscheidung erscheint hier.</span>
      </div>
    </div>
  </section>
</template>
