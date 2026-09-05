<script setup>
import Icon from './Icon.vue'
import { formatSize } from '../api'
defineProps({
  albums: Array,
  selection: Array,
  busy: Boolean,
  canSort: Boolean,
  duplicates: Number,
  canUndo: Boolean,
  undoShortcut: String,
})
defineEmits(['move', 'trash', 'create', 'duplicates', 'filter-duplicates', 'gallery', 'undo', 'settings'])
const albumLooks = [
  { icon: 'plane', color: 'sand' },
  { icon: 'mountain', color: 'sage' },
  { icon: 'building', color: 'lavender' },
  { icon: 'camera', color: 'rose' },
  { icon: 'heart', color: 'peach' },
]
function look(album, index) {
  const name = album.name.toLowerCase()
  if (/reisen|urlaub|portugal/.test(name)) return albumLooks[0]
  if (/natur|draußen|berg/.test(name)) return albumLooks[1]
  if (/architektur|stadt/.test(name)) return albumLooks[2]
  if (/alltag|familie|moment/.test(name)) return albumLooks[3]
  if (/favorit|liebling/.test(name)) return albumLooks[4]
  return { icon: 'folder', color: albumLooks[index % 5].color }
}
</script>

<template>
  <aside class="action-panel" aria-label="Ziel-Alben und Aktionen">
    <button class="back-to-gallery" @click="$emit('gallery')">
      <Icon name="arrow" :size="14" /> Zur Galerie
    </button>
    <div class="action-heading">
      <span class="eyebrow">ALLES AN SEINEN PLATZ</span><Icon name="arrow" :size="17" />
    </div>
    <h2>Wohin geht’s?</h2>
    <p class="action-intro">Bilder auswählen. Album anklicken.<br />Erinnerungen aufbewahren.</p>

    <div class="selection-summary" :class="{ 'has-selection': selection.length }" aria-live="polite">
      <span class="selection-icon"><Icon :name="selection.length ? 'check' : 'images'" :size="21" /></span>
      <div>
        <strong>{{
          selection.length
            ? `${selection.length} ${selection.length === 1 ? 'Bild' : 'Bilder'} ausgewählt`
            : 'Deine Auswahl'
        }}</strong
        ><span>{{
          selection.length
            ? `${formatSize(selection.reduce((total, image) => total + image.size, 0))} · bereit zum Sortieren`
            : 'Wähle Bilder in der Galerie'
        }}</span>
      </div>
    </div>

    <div class="album-workspace-actions" role="group" aria-label="Bibliotheksaktionen">
      <button
        class="undo-button"
        :disabled="!canUndo || busy"
        title="Letzte Verschiebeaktion rückgängig machen (Strg/⌘ + Z)"
        @click="$emit('undo')"
      >
        <Icon name="undo" :size="16" /><span>Rückgängig</span><kbd>{{ undoShortcut }}</kbd>
      </button>
      <button
        class="icon-button settings-button"
        aria-label="Bibliothek und Einstellungen"
        title="Bibliothek und Einstellungen"
        @click="$emit('settings')"
      >
        <Icon name="settings" :size="19" />
      </button>
    </div>

    <div class="section-label">
      <span>IN ALBUM VERSCHIEBEN</span><span class="subtle-count">{{ albums.length }}</span>
    </div>
    <div class="album-list">
      <button
        v-for="(album, index) in albums"
        :key="album.path"
        class="album-target"
        :disabled="busy || !canSort || !selection.length"
        :title="selection.length ? `Nach ${album.target} verschieben` : 'Wähle zuerst Bilder im Eingang aus'"
        @click="$emit('move', album.target)"
      >
        <span class="album-icon" :class="look(album, index).color"
          ><Icon :name="look(album, index).icon" :size="20"
        /></span>
        <span class="album-text"
          ><strong>{{ album.target }}</strong
          ><small>{{ album.count }} {{ album.count === 1 ? 'Bild' : 'Bilder' }}</small></span
        >
        <Icon class="album-arrow" name="chevron" :size="15" />
      </button>
      <p v-if="!albums.length" class="no-albums">Ein neues Album ist der Anfang einer guten Sammlung.</p>
    </div>
    <button class="new-album-button" :disabled="busy" @click="$emit('create')">
      <Icon name="plus" :size="17" /> Neues Album erstellen
    </button>

    <div v-if="duplicates && canSort" class="duplicate-notice">
      <div class="duplicate-notice-heading">
        <Icon name="copy" :size="16" /><strong
          >{{ duplicates }} {{ duplicates === 1 ? 'Duplikat erkannt' : 'Duplikate erkannt' }}</strong
        >
      </div>
      <p>Schon in einem Album. Doppelt<br />aufheben muss nicht sein.</p>
      <button @click="$emit('filter-duplicates', 'gallery')">
        Duplikate ansehen <Icon name="arrow" :size="14" />
      </button>
    </div>
    <button
      v-if="canSort && selection.length && selection.every((image) => image.is_duplicate)"
      class="button duplicate-action"
      :disabled="busy"
      @click="$emit('duplicates')"
    >
      <Icon name="copy" :size="16" /> In Duplikate ablegen
    </button>
    <div class="trash-area">
      <button class="trash-button" :disabled="busy || !canSort || !selection.length" @click="$emit('trash')">
        <Icon name="trash" :size="17" /> In den Papierkorb <kbd>Entf</kbd>
      </button>
      <span><Icon name="undo" :size="12" /> Jederzeit rückgängig machen.</span>
    </div>
    <div class="action-tip">
      <span class="tip-icon"><Icon name="keyboard" :size="18" /></span>
      <p>Ein kleiner Shortcut.<br /><strong>1–9</strong> verschiebt direkt ins Album.</p>
    </div>
  </aside>
</template>
