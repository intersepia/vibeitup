<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, flattenAlbums } from '../api'
import Icon from './Icon.vue'
import Modal from './Modal.vue'

const props = defineProps({
  initialParent: { type: String, default: '' },
  selectionCount: { type: Number, default: 0 },
  busy: Boolean,
  error: { type: String, default: '' },
})
const emit = defineEmits(['close', 'submit', 'clear-error'])
const name = ref('')
const parent = ref(props.initialParent)
const moveAfterCreate = ref(false)
const parents = ref([])
const loadingParents = ref(true)
const parentError = ref('')
let active = true

const parentAvailable = computed(
  () => parent.value === '' || parents.value.some((album) => album.target === parent.value),
)
const relativePath = computed(() =>
  [parent.value, name.value.trim() || 'Neues Album'].filter(Boolean).join('/'),
)
const pathTooLong = computed(() => Boolean(name.value.trim()) && Array.from(relativePath.value).length > 500)
const canSubmit = computed(
  () =>
    !props.busy &&
    !loadingParents.value &&
    !parentError.value &&
    parentAvailable.value &&
    !pathTooLong.value &&
    Boolean(name.value.trim()),
)

async function loadParents() {
  loadingParents.value = true
  parentError.value = ''
  try {
    const nodes = await api('/folders/albums')
    if (active) parents.value = flattenAlbums(nodes)
  } catch (error) {
    if (active) parentError.value = `Ordnerliste konnte nicht geladen werden: ${error.message}`
  } finally {
    if (active) loadingParents.value = false
  }
}

function submit() {
  if (!canSubmit.value) return
  emit('submit', { name: name.value.trim(), parent: parent.value, moveAfterCreate: moveAfterCreate.value })
}

watch([name, parent], () => emit('clear-error'))
onMounted(loadParents)
onBeforeUnmount(() => {
  active = false
})
</script>

<template>
  <Modal title="Ein neues Zuhause für deine Bilder." :closable="!busy" @close="$emit('close')">
    <form class="dialog-body album-form" @submit.prevent="submit">
      <span class="dialog-symbol sage"><Icon name="folder" :size="25" /></span>
      <p>Gib deinem Album einen Namen und wähle, wo es liegen soll.</p>

      <label class="form-label" for="album-name">Albumname</label>
      <input
        id="album-name"
        v-model="name"
        class="text-input"
        placeholder="Zum Beispiel: Sommer in Portugal"
        maxlength="100"
        required
        autofocus
        :disabled="busy"
      />

      <div class="album-parent-heading">
        <label class="form-label" for="album-parent">Übergeordneter Ordner</label>
        <button
          type="button"
          class="album-parent-refresh"
          :disabled="busy || loadingParents"
          aria-label="Ordnerliste aktualisieren"
          title="Ordnerliste aktualisieren"
          @click="loadParents"
        >
          <Icon name="refresh" :size="14" :class="{ spinning: loadingParents }" />
        </button>
      </div>
      <div class="album-parent-field">
        <Icon name="folder-open" :size="17" />
        <select
          id="album-parent"
          v-model="parent"
          class="text-input album-parent-select"
          :disabled="busy || loadingParents || Boolean(parentError)"
          :aria-invalid="!loadingParents && !parentAvailable"
          aria-describedby="album-parent-hint"
        >
          <option value="">Alle Alben (Hauptordner)</option>
          <option v-if="parent && !parentAvailable" :value="parent" disabled>
            {{ parent }} — nicht verfügbar
          </option>
          <option v-for="album in parents" :key="album.path" :value="album.target">
            {{ album.target.split('/').join(' / ') }}
          </option>
        </select>
        <Icon name="down" :size="14" />
      </div>
      <span id="album-parent-hint" class="form-hint">
        {{
          loadingParents
            ? 'Vorhandene Ordner werden geladen …'
            : 'Direkt im Hauptordner oder als Unteralbum eines vorhandenen Ordners.'
        }}
      </span>

      <div class="album-destination">
        <Icon name="folder" :size="19" />
        <div>
          <span>Ziel relativ zum Album-Hauptordner <code>alben/</code></span>
          <output aria-label="Relativer Album-Pfad" aria-live="polite" aria-atomic="true">{{
            relativePath
          }}</output>
        </div>
      </div>

      <p v-if="parentError" class="form-error" role="alert">
        {{ parentError }} Bitte die Ordnerliste aktualisieren.
      </p>
      <p v-else-if="!loadingParents && !parentAvailable" class="form-error" role="alert">
        Der gewählte Ordner ist nicht mehr verfügbar. Bitte wähle einen anderen Ordner. Es wird nicht
        automatisch im Hauptordner gespeichert.
      </p>
      <p v-if="pathTooLong" class="form-error" role="alert">
        Der relative Album-Pfad darf höchstens 500 Zeichen lang sein.
      </p>
      <label v-if="selectionCount" class="form-checkbox">
        <input v-model="moveAfterCreate" type="checkbox" :disabled="busy" />
        {{ selectionCount }} {{ selectionCount === 1 ? 'ausgewähltes Bild' : 'ausgewählte Bilder' }} direkt
        hierhin verschieben
      </label>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <div class="dialog-actions">
        <button type="button" class="button" :disabled="busy" @click="$emit('close')">Abbrechen</button>
        <button class="button primary" :disabled="!canSubmit">
          <Icon :name="busy ? 'refresh' : 'plus'" :class="{ spinning: busy }" :size="16" />
          {{ busy ? 'Wird angelegt …' : 'Album erstellen' }}
        </button>
      </div>
    </form>
  </Modal>
</template>
