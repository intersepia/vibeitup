<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useLibrary } from '../composables/useLibrary'
import { albumTarget, api, formatSize, imageUrl } from '../api'
import Icon from '../components/Icon.vue'
import SourceTree from '../components/SourceTree.vue'
import ImageCard from '../components/ImageCard.vue'
import AlbumPanel from '../components/AlbumPanel.vue'
import AlbumDialog from '../components/AlbumDialog.vue'
import ActivityLog from '../components/ActivityLog.vue'
import Modal from '../components/Modal.vue'

const library = useLibrary()
const {
  status,
  source,
  albums,
  images,
  logs,
  events,
  folder,
  recursive,
  filter,
  search,
  sort,
  ascending,
  selected,
  loading,
  galleryLoading,
  busy,
  scanning,
  online,
  error,
  mutationError,
  toast,
  isSource,
  visibleImages,
  selection,
  allSelected,
  duplicateCount,
} = library
const modal = ref(null)
const previewPath = ref(null)
const activityExpanded = ref(true)
const mobileNav = ref(false)
const sourceSidebar = ref(null)
const sourceToggle = ref(null)
const sourceClose = ref(null)
const sidebarMedia = window.matchMedia('(max-width: 840px)')
const sidebarAsDrawer = ref(sidebarMedia.matches)
const drawerOpen = computed(() => sidebarAsDrawer.value && mobileNav.value)
let drawerOverflow = ''

async function afterNavigationLayout() {
  await nextTick()
  // Let visibility and inert changes reach layout before moving keyboard focus.
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)))
}

watch(drawerOpen, async (open) => {
  if (open) {
    drawerOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    await afterNavigationLayout()
    if (drawerOpen.value && !modal.value) sourceClose.value?.focus()
  } else {
    document.body.style.overflow = drawerOverflow
    await afterNavigationLayout()
    if (sidebarAsDrawer.value && !drawerOpen.value && !modal.value)
      sourceToggle.value?.focus({ preventScroll: true })
  }
})
function updateSidebarMedia(event) {
  sidebarAsDrawer.value = event.matches
  if (!event.matches) mobileNav.value = false
}
const view = ref('grid')
const undoShortcut = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘ Z' : 'Strg Z'
const renderLimit = ref(80)
const searchInput = ref(null)
const history = ref([])
const historyLoading = ref(false)
const historyError = ref('')
const hasMoreHistory = ref(false)
try {
  view.value = localStorage.getItem('folio-view') === 'list' ? 'list' : 'grid'
} catch {
  /* Storage may be unavailable in private browsing. */
}

const working = computed(() => busy.value || scanning.value)
const root = computed(() => folder.value.split('/')[0])
const title = computed(() => {
  if (folder.value.includes('/')) return folder.value.split('/').at(-1)
  return (
    { zur_sortieren: 'Zu sortieren', alben: 'Deine Alben', duplikate: 'Duplikate', trash: 'Papierkorb' }[
      folder.value
    ] || 'Deine Bilder'
  )
})
const renderedImages = computed(() => visibleImages.value.slice(0, renderLimit.value))
watch(visibleImages, () => {
  renderLimit.value = 80
})
const preview = computed(() => visibleImages.value.find((image) => image.path === previewPath.value))
watch(preview, (image) => {
  if (modal.value === 'preview' && !image) modal.value = null
})
const previewIndex = computed(() =>
  visibleImages.value.findIndex((image) => image.path === previewPath.value),
)
const visibleSize = computed(() => visibleImages.value.reduce((sum, image) => sum + image.size, 0))
const totalFiles = computed(
  () =>
    status.value.source_count +
    status.value.album_images +
    status.value.duplicate_files +
    status.value.trash_count,
)

function setView(value) {
  view.value = value
  try {
    localStorage.setItem('folio-view', value)
  } catch {
    /* Optional preference. */
  }
}
function navigate(path, includeChildren = true) {
  mobileNav.value = false
  library.navigate(path, includeChildren)
}
function focusAlbums() {
  const panel = document.querySelector('.action-panel')
  panel?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  panel?.querySelector('.album-target:not(:disabled)')?.focus({ preventScroll: true })
}
function focusGallery() {
  document.querySelector('.gallery-panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}
function focusAlbumActions() {
  const panel = document.querySelector('.action-panel')
  panel?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  panel?.querySelector('.album-workspace-actions button:not(:disabled)')?.focus({ preventScroll: true })
}
async function openSettings() {
  if (drawerOpen.value) {
    mobileNav.value = false
    await afterNavigationLayout()
    sourceToggle.value?.focus({ preventScroll: true })
  }
  modal.value = 'settings'
}
function resetFilters() {
  search.value = ''
  filter.value = 'all'
}
function openAlbum() {
  if (working.value || loading.value) return
  mutationError.value = ''
  modal.value = 'album'
}
async function submitAlbum({ name, parent, moveAfterCreate }) {
  const album = await library.createAlbum(name, parent)
  if (!album) return
  modal.value = null
  // Use the canonical returned path, never only the leaf name: the same name
  // can legitimately exist under multiple parents (or directly in the root).
  if (moveAfterCreate && selection.value.length) await library.mutate('move', albumTarget(album.path))
}
function openTrash() {
  if (selection.value.length && isSource.value && !working.value) {
    mutationError.value = ''
    modal.value = 'trash'
  }
}
async function confirmTrash() {
  if (await library.mutate('trash')) modal.value = null
}
function openPreview(path) {
  previewPath.value = path
  modal.value = 'preview'
}
function stepPreview(direction) {
  const next = (previewIndex.value + direction + visibleImages.value.length) % visibleImages.value.length
  previewPath.value = visibleImages.value[next]?.path
}
async function openHistory() {
  modal.value = 'history'
  history.value = []
  await loadHistory()
}
async function loadHistory() {
  if (historyLoading.value) return
  historyLoading.value = true
  historyError.value = ''
  try {
    const rows = await api(`/logs?limit=25&offset=${history.value.length}`)
    history.value.push(...rows)
    hasMoreHistory.value = rows.length === 25
  } catch (err) {
    historyError.value = err.message
  } finally {
    historyLoading.value = false
  }
}
function historyLabel(log) {
  return (
    { move: 'Ins Album verschoben', trash: 'In den Papierkorb', duplicates: 'Duplikate abgelegt' }[
      log.action
    ] || log.action
  )
}
function historyStatus(log) {
  return (
    {
      completed: 'Abgeschlossen',
      undone: 'Rückgängig gemacht',
      rolled_back: 'Zurückgesetzt',
      interrupted: 'Prüfung nötig',
      pending: 'In Bearbeitung',
      undoing: 'Wird zurückgesetzt',
    }[log.status] || log.status
  )
}
function dateTime(value) {
  return new Date(value).toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short' })
}
function handleKeyboard(event) {
  if (drawerOpen.value && !modal.value) {
    if (event.key === 'Escape') {
      event.preventDefault()
      mobileNav.value = false
    } else if (event.key === 'Tab') {
      const buttons = [...sourceSidebar.value.querySelectorAll('button:not(:disabled)')].filter(
        (button) => button.offsetParent !== null,
      )
      const first = buttons[0]
      const last = buttons.at(-1)
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last?.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first?.focus()
      }
    }
    return
  }
  if (modal.value === 'preview') {
    if (event.key === 'ArrowLeft') {
      event.preventDefault()
      stepPreview(-1)
    }
    if (event.key === 'ArrowRight') {
      event.preventDefault()
      stepPreview(1)
    }
  }
  if (event.key === 'Escape' && !working.value) {
    modal.value = null
    mobileNav.value = false
    library.clearSelection()
    return
  }
  if (
    modal.value ||
    working.value ||
    event.target.closest('input, textarea, select, [contenteditable="true"]')
  )
    return
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'a') {
    event.preventDefault()
    library.selectAll()
  } else if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
    event.preventDefault()
    if (status.value.can_undo) library.mutate('undo')
  } else if (event.key === 'Delete') {
    event.preventDefault()
    openTrash()
  } else if (event.key === '/') {
    event.preventDefault()
    searchInput.value?.focus()
  } else if (event.key === '?') {
    modal.value = 'shortcuts'
  } else if (
    /^[1-9]$/.test(event.key) &&
    !event.ctrlKey &&
    !event.metaKey &&
    !event.altKey &&
    selection.value.length
  ) {
    const album = albums.value[Number(event.key) - 1]
    if (album) {
      event.preventDefault()
      library.mutate('move', album.target)
    }
  }
}
onMounted(() => {
  library.initialize()
  window.addEventListener('keydown', handleKeyboard)
  sidebarMedia.addEventListener('change', updateSidebarMedia)
})
onBeforeUnmount(() => {
  window.removeEventListener('keydown', handleKeyboard)
  sidebarMedia.removeEventListener('change', updateSidebarMedia)
  if (drawerOpen.value) document.body.style.overflow = drawerOverflow
})
</script>

<template>
  <div class="folio-app" :inert="Boolean(modal)" :aria-hidden="modal ? true : undefined">
    <main class="workspace-shell">
      <div v-if="drawerOpen" class="mobile-nav-scrim" aria-hidden="true" @click="mobileNav = false"></div>
      <aside
        id="source-navigation"
        ref="sourceSidebar"
        class="source-sidebar"
        :class="{ 'mobile-open': drawerOpen }"
        :inert="sidebarAsDrawer && !mobileNav"
        :aria-hidden="sidebarAsDrawer && !mobileNav ? true : undefined"
        :role="drawerOpen ? 'dialog' : undefined"
        :aria-modal="drawerOpen ? true : undefined"
        aria-label="Quell-Navigation"
      >
        <div class="sidebar-brand">
          <button class="brand" aria-label="Folio – zurück zum Eingang" @click="navigate('zur_sortieren')">
            <span class="brand-mark"
              ><svg viewBox="0 0 40 40" fill="none" aria-hidden="true">
                <rect
                  x="9"
                  y="8"
                  width="18"
                  height="23"
                  rx="3"
                  transform="rotate(-12 9 8)"
                  stroke="currentColor"
                  stroke-width="1.7"
                />
                <rect
                  x="14"
                  y="11"
                  width="18"
                  height="23"
                  rx="3"
                  fill="#2d4437"
                  stroke="currentColor"
                  stroke-width="1.7"
                />
                <path
                  d="m15 28 5-6 5 5 3-3 3 4"
                  stroke="currentColor"
                  stroke-width="1.7"
                  stroke-linejoin="round"
                />
                <circle cx="25.5" cy="18" r="2" fill="currentColor" /></svg
            ></span>
            <span class="brand-name">folio<span>.</span></span>
          </button>
          <button
            ref="sourceClose"
            class="icon-button source-nav-close"
            aria-label="Quell-Navigation schließen"
            @click="mobileNav = false"
          >
            <Icon name="close" :size="18" />
          </button>
        </div>
        <div class="sidebar-scroll">
          <div class="sidebar-section-title">
            <span>DEINE BIBLIOTHEK</span><span class="tiny-label">LOCAL</span>
          </div>
          <nav class="main-navigation">
            <button
              class="nav-item"
              :class="{ active: folder === 'zur_sortieren' }"
              :disabled="working"
              @click="navigate('zur_sortieren')"
            >
              <Icon name="inbox" :size="19" /><span>Eingang</span
              ><span class="nav-count">{{ status.source_count }}</span>
            </button>
            <button
              class="nav-item"
              :class="{ active: root === 'alben' }"
              :disabled="working"
              @click="navigate('alben')"
            >
              <Icon name="images" :size="19" /><span>Alle Alben</span
              ><span class="plain-count">{{ status.album_images }}</span>
            </button>
          </nav>
          <div class="source-folders">
            <div class="sidebar-section-title">
              <span>QUELLORDNER</span><Icon name="folder-open" :size="13" />
            </div>
            <button
              class="source-root"
              :class="{ selected: folder === 'zur_sortieren' && !recursive }"
              :disabled="working"
              title="Nur Bilder direkt in zur_sortieren anzeigen"
              @click="navigate('zur_sortieren', false)"
            >
              <Icon name="down" :size="12" /><Icon name="folder-open" :size="16" /><span>zur_sortieren</span>
            </button>
            <SourceTree :nodes="source.children" :active="folder" @navigate="navigate" />
            <p v-if="!source.children.length && !loading" class="sidebar-empty">
              Neue Unterordner erscheinen<br />nach dem Einlesen hier.
            </p>
          </div>
          <div class="filing-navigation">
            <div class="sidebar-section-title"><span>ABLAGE</span></div>
            <button
              class="nav-item"
              :class="{ active: root === 'duplikate' }"
              :disabled="working"
              @click="navigate('duplikate')"
            >
              <Icon name="copy" :size="18" /><span>Duplikate</span
              ><span v-if="status.duplicate_files" class="plain-count">{{ status.duplicate_files }}</span>
            </button>
            <button
              class="nav-item"
              :class="{ active: root === 'trash' }"
              :disabled="working"
              @click="navigate('trash')"
            >
              <Icon name="trash" :size="18" /><span>Papierkorb</span
              ><span v-if="status.trash_count" class="plain-count">{{ status.trash_count }}</span>
            </button>
          </div>
        </div>
        <div class="sidebar-bottom">
          <div class="privacy-card">
            <span class="privacy-icon"><Icon name="shield" :size="22" /></span>
            <h3>Deine Bilder bleiben deine.</h3>
            <p>Keine Cloud. Kein Upload.<br />Nur du und deine Erinnerungen.</p>
            <div class="privacy-decoration">
              <span></span><span></span><span></span><Icon name="lock" :size="12" />
            </div>
          </div>
          <button class="rescan-sidebar" :disabled="working" @click="library.rescan()">
            <Icon name="refresh" :class="{ spinning: scanning }" :size="15" /><span>{{
              scanning ? 'Wird eingelesen …' : 'Ordner neu einlesen'
            }}</span>
          </button>
          <div class="library-location">
            <Icon name="laptop" :size="13" /><span>Lokale Bibliothek</span
            ><button aria-label="Speicherort anzeigen" @click="openSettings">
              <Icon name="info" :size="13" />
            </button>
          </div>
        </div>
      </aside>

      <section
        class="gallery-panel"
        :inert="drawerOpen"
        :aria-hidden="drawerOpen ? true : undefined"
        aria-label="Bildergalerie"
      >
        <div class="gallery-top">
          <div class="filter-toolbar" role="group" aria-label="Galerie-Werkzeugleiste">
            <div class="gallery-title-group">
              <button
                ref="sourceToggle"
                class="mobile-nav-toggle icon-button"
                aria-label="Quell-Navigation öffnen"
                aria-controls="source-navigation"
                :aria-expanded="drawerOpen"
                @click="mobileNav = true"
              >
                <Icon name="menu" :size="18" />
              </button>
              <h1 class="gallery-title" :title="title">{{ title }}</h1>
              <button
                class="mobile-actions-jump icon-button"
                aria-label="Zu Alben und Aktionen"
                title="Zu Alben und Aktionen"
                @click="focusAlbumActions"
              >
                <Icon name="folder-open" :size="17" />
              </button>
            </div>
            <div class="gallery-tabs" role="tablist" aria-label="Bildfilter">
              <button
                role="tab"
                :aria-selected="filter === 'all'"
                :class="{ active: filter === 'all' }"
                @click="filter = 'all'"
              >
                <span>Alle Bilder</span><small>{{ images.length }}</small>
              </button>
              <button
                v-if="isSource"
                role="tab"
                :aria-selected="filter === 'duplicates'"
                :class="{ active: filter === 'duplicates' }"
                @click="filter = 'duplicates'"
              >
                <Icon name="copy" :size="13" /><span>Duplikate</span
                ><small :class="{ amber: duplicateCount }">{{ duplicateCount }}</small>
              </button>
            </div>
            <div class="search-field">
              <Icon name="search" :size="16" /><input
                ref="searchInput"
                v-model="search"
                type="search"
                aria-label="Bilder suchen"
                placeholder="Suchen …"
              /><kbd v-if="!search">/</kbd
              ><button v-else aria-label="Suche löschen" @click="search = ''">
                <Icon name="close" :size="13" />
              </button>
            </div>
            <div class="gallery-view-switch" role="group" aria-label="Galerieansicht">
              <button
                :class="{ active: view === 'grid' }"
                :aria-pressed="view === 'grid'"
                aria-label="Rasteransicht"
                @click="setView('grid')"
              >
                <Icon name="grid" :size="17" /></button
              ><button
                :class="{ active: view === 'list' }"
                :aria-pressed="view === 'list'"
                aria-label="Listenansicht"
                @click="setView('list')"
              >
                <Icon name="list" :size="19" />
              </button>
            </div>
          </div>
          <div v-if="status.index_warning" class="index-warning" role="alert">
            <Icon name="warning" :size="17" />
            <span>{{ status.index_warning }}</span>
            <button :disabled="working" @click="library.rescan()">Neu einlesen</button>
          </div>
          <div class="gallery-controls">
            <button
              v-if="isSource"
              class="select-all"
              role="checkbox"
              :aria-checked="allSelected ? true : selection.length ? 'mixed' : false"
              :disabled="working || !visibleImages.length"
              @click="library.selectAll()"
            >
              <span class="small-checkbox" :class="{ checked: selected.size }"
                ><Icon
                  v-if="selected.size"
                  :name="allSelected ? 'check' : 'minus'"
                  :size="12"
                  :stroke="2.5" /></span
              >{{ allSelected ? 'Auswahl aufheben' : 'Alle auswählen' }}
            </button>
            <span v-else class="read-only-label"><Icon name="lock" :size="13" /> Nur ansehen</span>
            <div class="sort-controls">
              <span class="folder-context" :title="folder"
                ><Icon name="folder" :size="12" />{{
                  folder === 'zur_sortieren' && recursive ? 'Alle Quellordner' : folder.split('/').at(-1)
                }}</span
              ><span class="control-divider"></span
              ><label
                ><span class="sr-only">Bilder sortieren</span
                ><select v-model="sort">
                  <option value="name">Dateiname</option>
                  <option value="date">Datum</option>
                  <option value="size">Dateigröße</option></select
                ><Icon name="down" :size="12" /></label
              ><button
                class="sort-direction"
                :aria-label="ascending ? 'Absteigend sortieren' : 'Aufsteigend sortieren'"
                @click="ascending = !ascending"
              >
                <span>{{ ascending ? '↑' : '↓' }}</span>
              </button>
            </div>
          </div>
        </div>

        <div class="gallery-viewport" :aria-busy="loading || galleryLoading || working">
          <div v-if="error" class="empty-state error-state">
            <div class="empty-symbol"><Icon name="warning" :size="32" /></div>
            <h2>Kurz die Verbindung prüfen.</h2>
            <p>{{ error }}</p>
            <button class="button primary" @click="library.initialize()">
              <Icon name="refresh" :size="16" /> Erneut versuchen
            </button>
          </div>
          <div
            v-else-if="loading || galleryLoading"
            class="image-grid"
            :class="{ 'list-layout': view === 'list' }"
          >
            <div v-for="i in 12" :key="i" class="skeleton-card">
              <div></div>
              <span></span><small></small>
            </div>
          </div>
          <template v-else-if="visibleImages.length">
            <div class="image-grid" :class="{ 'list-layout': view === 'list' }">
              <ImageCard
                v-for="(image, index) in renderedImages"
                :key="image.path"
                :image="image"
                :index="index"
                :selected="selected.has(image.path)"
                :selectable="isSource && !working"
                :list="view === 'list'"
                @select="library.select(image, index, $event)"
                @preview="openPreview(image.path)"
              />
            </div>
            <div v-if="renderLimit < visibleImages.length" class="gallery-more">
              <button class="button" @click="renderLimit += 80">
                Weitere {{ Math.min(80, visibleImages.length - renderLimit) }} Bilder anzeigen
                <Icon name="down" :size="15" />
              </button>
            </div>
            <div class="gallery-bottom-note">
              <span
                >{{ visibleImages.length }} {{ visibleImages.length === 1 ? 'Bild' : 'Bilder' }}<span>·</span
                >{{ formatSize(visibleSize) }}</span
              ><span><Icon name="expand" :size="12" /> Doppelklick für die große Ansicht</span>
            </div>
          </template>
          <div v-else-if="search || filter === 'duplicates'" class="empty-state">
            <div class="empty-symbol">
              <Icon :name="filter === 'duplicates' ? 'sparkle' : 'search'" :size="32" />
            </div>
            <h2>{{ search ? 'Noch kein Treffer.' : 'Alles einmalig.' }}</h2>
            <p>
              {{
                search
                  ? 'Versuch es mit einem anderen Dateinamen oder Ordner.'
                  : 'In diesem Ordner gibt es keine identischen Bilder, die schon in einem Album liegen.'
              }}
            </p>
            <button class="button" @click="resetFilters">
              Alle Bilder anzeigen <Icon name="arrow" :size="15" />
            </button>
          </div>
          <div v-else class="empty-state">
            <div class="empty-illustration">
              <div></div>
              <div>
                <Icon :name="isSource ? 'images' : root === 'trash' ? 'trash' : 'folder'" :size="40" />
              </div>
              <span><Icon name="check" :size="16" /></span>
            </div>
            <span class="eyebrow">{{ isSource ? 'RAUM FÜR NEUE ERINNERUNGEN' : 'ALLES AUFGERÄUMT' }}</span>
            <h2>{{ isSource ? 'Ein bisschen weniger Chaos.' : 'Hier ist es noch ganz ruhig.' }}</h2>
            <p>
              {{
                isSource
                  ? 'Lege deine Bilder in den Eingangsordner und lies die Bibliothek neu ein. Der Rest ist ein guter Anfang.'
                  : 'Hier erscheinen Bilder, sobald du sie aus dem Eingang in diesen Ordner verschiebst.'
              }}
            </p>
            <code v-if="isSource" class="empty-path">{{ status.base_path }}/{{ folder }}</code
            ><button v-if="isSource" class="button primary" :disabled="working" @click="library.rescan()">
              <Icon name="refresh" :size="16" /> Bilder einlesen</button
            ><button v-else class="button primary" @click="navigate('zur_sortieren')">
              Zum Eingang <Icon name="arrow" :size="16" />
            </button>
          </div>
        </div>

        <div v-if="selection.length" class="selection-bar">
          <div>
            <span class="selection-bar-count">{{ selection.length }}</span
            ><strong>{{ selection.length === 1 ? 'Bild ausgewählt' : 'Bilder ausgewählt' }}</strong
            ><button aria-label="Auswahl aufheben" @click="library.clearSelection()">
              <Icon name="close" :size="14" />
            </button>
          </div>
          <button class="selection-next" @click="focusAlbums">
            Jetzt ein Album wählen <Icon name="arrow" :size="16" />
          </button>
        </div>
        <ActivityLog
          :logs="logs"
          :events="events"
          :expanded="activityExpanded"
          :indexed-at="status.last_indexed_at"
          @toggle="activityExpanded = !activityExpanded"
          @show-all="openHistory"
        />
      </section>

      <AlbumPanel
        :inert="drawerOpen"
        :aria-hidden="drawerOpen ? true : undefined"
        :can-undo="status.can_undo"
        :undo-shortcut="undoShortcut"
        @undo="library.mutate('undo')"
        @settings="openSettings"
        :albums="albums"
        :selection="selection"
        :busy="working || loading"
        :can-sort="isSource"
        :duplicates="duplicateCount"
        @move="library.mutate('move', $event)"
        @trash="openTrash"
        @create="openAlbum"
        @duplicates="library.mutate('duplicates')"
        @filter-duplicates="library.showDuplicates()"
        @gallery="focusGallery"
      />
    </main>

    <footer class="app-footer" :inert="drawerOpen" :aria-hidden="drawerOpen ? true : undefined">
      <div>
        <span class="connection-dot" :class="{ offline: !online }"></span
        ><span>{{
          working
            ? scanning
              ? 'Bibliothek wird eingelesen …'
              : 'Bilder werden sicher verschoben …'
            : online
              ? 'Alles lokal. Alles unter Kontrolle.'
              : 'Verbindung wird benötigt'
        }}</span>
      </div>
      <div class="footer-library-stats">
        <span>{{ totalFiles }} Bilder</span><span>·</span><span>{{ formatSize(status.total_size) }}</span
        ><span v-if="status.demo" class="demo-badge">Demo-Bibliothek</span>
      </div>
      <button @click="modal = 'shortcuts'">
        <Icon name="keyboard" :size="14" /> Tastenkürzel <kbd>?</kbd></button
      ><span class="footer-version">folio v1.0</span>
    </footer>

    <Transition name="toast"
      ><div
        v-if="toast"
        class="toast-message"
        :class="toast.type"
        :role="toast.type === 'error' ? 'alert' : 'status'"
      >
        <span class="toast-icon"
          ><Icon
            :name="toast.type === 'error' ? 'warning' : toast.type === 'info' ? 'info' : 'check'"
            :size="18" /></span
        ><span>{{ toast.message }}</span
        ><button v-if="toast.undo" class="toast-undo" :disabled="working" @click="library.mutate('undo')">
          Rückgängig</button
        ><button class="toast-close" aria-label="Meldung schließen" @click="toast = null">
          <Icon name="close" :size="16" />
        </button></div
    ></Transition>

    <AlbumDialog
      v-if="modal === 'album'"
      :initial-parent="root === 'alben' ? albumTarget(folder) : ''"
      :selection-count="selection.length"
      :busy="working"
      :error="mutationError"
      @submit="submitAlbum"
      @clear-error="mutationError = ''"
      @close="modal = null"
    />

    <Modal
      v-if="modal === 'trash'"
      title="Platz für die guten Bilder."
      :closable="!busy"
      @close="modal = null"
    >
      <div class="dialog-body">
        <div class="trash-preview">
          <img
            v-for="image in selection.slice(0, 4)"
            :key="image.path"
            :src="imageUrl(image.path)"
            :alt="image.name"
          /><span v-if="selection.length > 4">+{{ selection.length - 4 }}</span>
        </div>
        <h3>{{ selection.length }} {{ selection.length === 1 ? 'Bild' : 'Bilder' }} aussortieren?</h3>
        <p>
          Die Auswahl wird in <code>trash/</code> verschoben, nicht endgültig gelöscht. Du kannst die gesamte
          Aktion rückgängig machen.
        </p>
        <p v-if="mutationError" class="form-error" role="alert">{{ mutationError }}</p>
        <div class="dialog-actions">
          <button class="button" :disabled="busy" @click="modal = null">Lieber behalten</button
          ><button class="button danger" :disabled="busy" @click="confirmTrash">
            <Icon name="trash" :size="16" />{{ busy ? 'Wird verschoben …' : 'In den Papierkorb' }}
          </button>
        </div>
      </div>
    </Modal>

    <Modal v-if="modal === 'preview' && preview" :title="preview.name" wide @close="modal = null">
      <div class="lightbox">
        <img :key="preview.path" :src="imageUrl(preview.path, true)" :alt="preview.name" /><button
          v-if="visibleImages.length > 1"
          class="lightbox-prev"
          aria-label="Vorheriges Bild"
          @click="stepPreview(-1)"
        >
          <Icon name="chevron" :size="24" /></button
        ><button
          v-if="visibleImages.length > 1"
          class="lightbox-next"
          aria-label="Nächstes Bild"
          @click="stepPreview(1)"
        >
          <Icon name="chevron" :size="24" />
        </button>
      </div>
      <div class="lightbox-meta">
        <div>
          <span>{{ previewIndex + 1 }} / {{ visibleImages.length }}</span
          ><span>{{ formatSize(preview.size) }}</span
          ><span v-if="preview.width">{{ preview.width }} × {{ preview.height }} px</span
          ><span>{{ preview.format }}</span>
        </div>
        <button
          v-if="isSource"
          class="button"
          :class="{ primary: selected.has(preview.path) }"
          @click="library.select(preview, previewIndex, $event)"
        >
          <Icon :name="selected.has(preview.path) ? 'check' : 'plus'" :size="16" />{{
            selected.has(preview.path) ? 'Ausgewählt' : 'Auswählen'
          }}
        </button>
      </div>
      <div class="preview-details">
        <p>
          <strong>Dateipfad</strong><code>{{ preview.path }}</code>
        </p>
        <p>
          <strong>SHA-1</strong><code>{{ preview.sha1 }}</code>
        </p>
        <p v-if="preview.is_duplicate" class="preview-duplicate">
          <Icon name="copy" :size="14" /> Bereits vorhanden in {{ preview.duplicate_of.join(', ') }}
        </p>
      </div>
    </Modal>

    <Modal v-if="modal === 'settings'" title="Dein Workspace. Auf deinem Gerät." @close="modal = null">
      <div class="dialog-body">
        <div class="settings-privacy">
          <Icon name="shield" :size="26" />
          <div>
            <strong>100 % lokal. Ganz bewusst.</strong>
            <p>Bilder, Index und Protokoll bleiben auf deiner Festplatte. Folio braucht keine Cloud.</p>
          </div>
        </div>
        <label class="form-label">Aktueller Bibliothekspfad</label
        ><code class="settings-path">{{ status.base_path || 'Noch nicht verbunden' }}</code>
        <p class="form-hint">
          Ändere <code>base_path</code> in <code>config.local.yaml</code> und starte Folio neu. Alternativ:
          <code>IMAGE_SORTER_BASE_PATH</code>.
        </p>
        <div class="managed-folders">
          <div
            v-for="item in [
              ['zur_sortieren/', 'Dein Eingang'],
              ['alben/', 'Sortierte Erinnerungen'],
              ['duplikate/', 'Exakt identische Bilder'],
              ['trash/', 'Aussortiert, nicht gelöscht'],
              ['temp/', 'Platz für Verarbeitungsergebnisse'],
            ]"
            :key="item[0]"
          >
            <Icon name="folder" :size="16" /><code>{{ item[0] }}</code
            ><span>{{ item[1] }}</span>
          </div>
        </div>
        <p v-if="status.demo" class="demo-info">
          <Icon name="info" :size="17" />Du siehst eine Demo-Bibliothek. Konfiguriere einen anderen Basis-Pfad
          für deine eigenen Bilder.
        </p>
        <p class="form-hint">
          Unterstützt: JPG, PNG, WebP, GIF, BMP, TIFF und AVIF. Vorschauen sind maximal 400 px groß; Originale
          werden nicht verändert.
        </p>
        <div class="dialog-actions">
          <button class="button primary" @click="modal = null">
            Alles klar <Icon name="check" :size="16" />
          </button>
        </div>
      </div>
    </Modal>

    <Modal v-if="modal === 'shortcuts'" title="Ein bisschen schneller sortieren." @close="modal = null">
      <div class="dialog-body">
        <p>Weniger Klicken, mehr gute Entscheidungen.</p>
        <div class="shortcut-list">
          <div><span>Bild zur Auswahl hinzufügen / entfernen</span><kbd>Klick / Strg + Klick</kbd></div>
          <div><span>Zusammenhängenden Bereich auswählen</span><kbd>Shift + Klick</kbd></div>
          <div><span>Alle sichtbaren Bilder auswählen</span><kbd>Strg / ⌘ + A</kbd></div>
          <div><span>Ins erste bis neunte Album verschieben</span><kbd>1 – 9</kbd></div>
          <div><span>In den Papierkorb verschieben</span><kbd>Entf</kbd></div>
          <div><span>Letzte Aktion rückgängig machen</span><kbd>Strg / ⌘ + Z</kbd></div>
          <div><span>Bilder suchen</span><kbd>/</kbd></div>
          <div><span>Auswahl aufheben / Dialog schließen</span><kbd>Esc</kbd></div>
          <div><span>Nächstes / vorheriges Bild in der Vorschau</span><kbd>← →</kbd></div>
        </div>
        <p class="form-hint">
          Die Album-Reihenfolge entspricht der Liste rechts. Pro Aktion sind bis zu 500 Bilder möglich.
        </p>
      </div>
    </Modal>

    <Modal v-if="modal === 'history'" title="Deine Sortiergeschichte." wide @close="modal = null">
      <div class="dialog-body history-body">
        <p>Jede Verschiebung hat eine Spur. Auch nach einem Neustart.</p>
        <div v-if="!history.length && !historyLoading && !historyError" class="history-empty">
          <Icon name="clock" :size="34" />
          <h3>Der Anfang einer aufgeräumten Bibliothek.</h3>
          <p>Sobald du Bilder verschiebst, findest du hier die vollständigen Transaktionen.</p>
        </div>
        <article v-for="log in history" :key="log.id" class="history-entry">
          <div class="history-entry-heading">
            <span class="history-icon"
              ><Icon
                :name="log.status === 'undone' ? 'undo' : log.action === 'trash' ? 'trash' : 'folder'"
                :size="19"
            /></span>
            <div>
              <h3>
                {{ historyLabel(log) }}
                <small>· {{ log.files.length }} {{ log.files.length === 1 ? 'Bild' : 'Bilder' }}</small>
              </h3>
              <time>{{ dateTime(log.created_at) }}</time>
            </div>
            <span class="history-status" :class="log.status">{{ historyStatus(log) }}</span>
          </div>
          <p v-if="log.error" class="form-error">{{ log.error }}</p>
          <details>
            <summary>
              Dateipfade & Transaktion <code>{{ log.id.slice(0, 8) }}</code>
            </summary>
            <div v-for="file in log.files" :key="file.source" class="history-file">
              <code>{{ file.source }}</code
              ><Icon name="arrow" :size="13" /><code>{{ file.destination }}</code>
            </div>
          </details>
        </article>
        <p v-if="historyError" class="form-error" role="alert">{{ historyError }}</p>
        <button
          v-if="hasMoreHistory || historyError"
          class="button history-more"
          :disabled="historyLoading"
          @click="loadHistory"
        >
          {{ historyError ? 'Erneut versuchen' : 'Weitere Aktivitäten laden' }}
        </button>
        <p v-if="historyLoading" class="history-loading">
          <Icon name="refresh" class="spinning" :size="16" /> Protokoll wird geladen …
        </p>
      </div>
    </Modal>
  </div>
</template>
