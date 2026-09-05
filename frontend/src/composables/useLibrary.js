import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { albumTarget, api, flattenAlbums, post } from '../api'

export function useLibrary() {
  const status = ref({
    source_count: 0,
    source_size: 0,
    album_count: 0,
    album_images: 0,
    duplicate_count: 0,
    duplicate_files: 0,
    trash_count: 0,
    total_size: 0,
    can_undo: false,
  })
  const source = ref({ children: [], direct_count: 0 })
  const albumTree = ref([])
  const albums = computed(() => flattenAlbums(albumTree.value))
  const images = ref([])
  const logs = ref([])
  const events = ref([])
  const folder = ref('zur_sortieren')
  const recursive = ref(true)
  const filter = ref('all')
  const search = ref('')
  const sort = ref('name')
  const ascending = ref(true)
  const selected = ref(new Set())
  const loading = ref(true)
  const galleryLoading = ref(false)
  const busy = ref(false)
  const scanning = ref(false)
  const online = ref(false)
  const error = ref('')
  const mutationError = ref('')
  const toast = ref(null)
  let toastTimer
  let imageRequest = 0
  let anchor = null
  const isSource = computed(
    () => folder.value === 'zur_sortieren' || folder.value.startsWith('zur_sortieren/'),
  )
  const collator = new Intl.Collator('de', { numeric: true, sensitivity: 'base' })
  const visibleImages = computed(() => {
    const needle = search.value.trim().toLocaleLowerCase('de-DE')
    return images.value
      .filter(
        (image) =>
          (filter.value !== 'duplicates' || image.is_duplicate) &&
          (!needle || image.path.toLocaleLowerCase('de-DE').includes(needle)),
      )
      .sort((a, b) => {
        let difference =
          sort.value === 'size'
            ? a.size - b.size
            : sort.value === 'date'
              ? new Date(a.modified_at) - new Date(b.modified_at)
              : collator.compare(a.name, b.name)
        if (!difference) difference = collator.compare(a.path, b.path)
        return ascending.value ? difference : -difference
      })
  })
  const selection = computed(() => images.value.filter((image) => selected.value.has(image.path)))
  const allSelected = computed(
    () =>
      visibleImages.value.length > 0 && visibleImages.value.every((image) => selected.value.has(image.path)),
  )
  const duplicateCount = computed(() => images.value.filter((image) => image.is_duplicate).length)

  function notify(message, type = 'success', undo = false) {
    clearTimeout(toastTimer)
    toast.value = { message, type, undo }
    toastTimer = setTimeout(
      () => {
        toast.value = null
      },
      type === 'error' ? 12000 : 6500,
    )
  }

  function addEvent(text) {
    events.value = [
      { id: `event-${Date.now()}`, date: new Date().toISOString(), text },
      ...events.value,
    ].slice(0, 20)
  }

  async function loadImages() {
    const id = ++imageRequest
    galleryLoading.value = true
    try {
      const data = await api(`/images?path=${encodeURIComponent(folder.value)}&recursive=${recursive.value}`)
      if (id === imageRequest) images.value = data.images
    } catch (err) {
      if (id === imageRequest) throw err
    } finally {
      if (id === imageRequest) galleryLoading.value = false
    }
  }

  async function refresh() {
    const [nextStatus, nextSource, nextAlbums, nextLogs] = await Promise.all([
      api('/status'),
      api('/folders/source'),
      api('/folders/albums'),
      api('/logs'),
    ])
    status.value = nextStatus
    source.value = nextSource
    albumTree.value = nextAlbums
    logs.value = nextLogs
    online.value = true
    await loadImages()
    error.value = ''
  }

  async function initialize() {
    loading.value = true
    try {
      await refresh()
    } catch (err) {
      error.value = err.message
      online.value = false
    } finally {
      loading.value = false
    }
  }

  async function navigate(path, includeChildren = true) {
    if (busy.value || scanning.value) return
    folder.value = path
    recursive.value = includeChildren
    filter.value = 'all'
    search.value = ''
    clearSelection()
    error.value = ''
    try {
      await loadImages()
    } catch (err) {
      error.value = err.message
      images.value = []
    }
  }

  async function rescan() {
    if (busy.value || scanning.value) return
    scanning.value = true
    try {
      const report = await post('/index')
      await refresh()
      addEvent(`Index aktualisiert · ${report.hashed} neu geprüft, ${report.cached} aus dem Cache`)
      notify(
        report.skipped
          ? `${report.skipped} Dateien konnten nicht gelesen werden. Details stehen im Serverprotokoll.`
          : `Alles aktuell. ${report.total} Bilder in deiner Bibliothek.`,
        report.skipped ? 'info' : 'success',
      )
    } catch (err) {
      notify(err.message, 'error')
    } finally {
      scanning.value = false
    }
  }

  function clearSelection() {
    selected.value = new Set()
    anchor = null
  }

  function select(image, index, event = {}) {
    if (!isSource.value || busy.value || scanning.value) return
    let next = new Set(selected.value)
    const anchorIndex = visibleImages.value.findIndex((item) => item.path === anchor)
    if (event.shiftKey && anchorIndex >= 0) {
      if (!event.ctrlKey && !event.metaKey) next.clear()
      const from = Math.min(anchorIndex, index)
      const to = Math.max(anchorIndex, index)
      visibleImages.value.slice(from, to + 1).forEach((item) => next.add(item.path))
    } else {
      next.has(image.path) ? next.delete(image.path) : next.add(image.path)
      anchor = image.path
    }
    if (next.size > 500) {
      notify('Bitte höchstens 500 Bilder pro Aktion auswählen.', 'info')
      return
    }
    selected.value = next
  }

  function selectAll() {
    if (!isSource.value || busy.value || scanning.value) return
    if (allSelected.value) {
      clearSelection()
      return
    }
    selected.value = new Set(visibleImages.value.slice(0, 500).map((image) => image.path))
    if (visibleImages.value.length > 500)
      notify(
        'Die ersten 500 Bilder sind ausgewählt. Große Ordner lassen sich so in sicheren Schritten sortieren.',
        'info',
      )
  }

  async function mutate(action, target) {
    if (busy.value || scanning.value) return null
    if (action !== 'undo' && !selection.value.length) return null
    mutationError.value = ''
    busy.value = true
    let result
    try {
      const body =
        action === 'undo'
          ? undefined
          : {
              files: selection.value.map((image) => image.path),
              ...(action === 'move' ? { target_album: target } : {}),
            }
      result = await post(`/action/${action}`, body)
    } catch (err) {
      mutationError.value = err.message
      notify(err.message, 'error')
      // A partial rollback may change the actual files. Refresh only after an HTTP
      // response, not after a connection timeout; retain any still-valid selection.
      if (err.status) {
        try {
          await refresh()
        } catch {
          /* Keep the original operation error visible. */
        }
      }
      busy.value = false
      return null
    }
    const count = result.files.length
    const noun = count === 1 ? 'Bild' : 'Bilder'
    if (action !== 'undo') {
      const moved = new Set(result.files.map((item) => item.source))
      images.value = images.value.filter((image) => !moved.has(image.path))
    }
    clearSelection()
    status.value.can_undo = action !== 'undo'
    notify(
      action === 'undo'
        ? `${count} ${noun} zurück im Eingang. Gute Entscheidung, nochmal hinzuschauen.`
        : `${count} ${noun} ${action === 'move' ? `nach „${target}“` : action === 'trash' ? 'in den Papierkorb' : 'in Duplikate'} verschoben.`,
      'success',
      action !== 'undo',
    )
    try {
      await refresh()
    } catch (err) {
      notify(`Aktion abgeschlossen. Die Ansicht konnte nicht aktualisiert werden: ${err.message}`, 'info')
    } finally {
      busy.value = false
    }
    return result
  }

  async function createAlbum(name, parent = '') {
    if (busy.value || scanning.value) return null
    mutationError.value = ''
    busy.value = true
    let album
    try {
      album = await post('/folders/albums', { name, parent })
    } catch (err) {
      mutationError.value = err.message
      busy.value = false
      return null
    }
    const target = albumTarget(album.path)
    addEvent(`Neues Album „${target}“ erstellt`)
    notify(`„${target}“ ist bereit für deine Bilder.`)
    try {
      await refresh()
    } catch (err) {
      notify(`Album erstellt. Bitte die Ansicht neu laden: ${err.message}`, 'info')
    } finally {
      busy.value = false
    }
    return album
  }

  async function showDuplicates() {
    if (!isSource.value) await navigate('zur_sortieren')
    filter.value = 'duplicates'
    search.value = ''
    clearSelection()
  }

  watch(visibleImages, (current) => {
    const available = new Set(current.map((image) => image.path))
    selected.value = new Set([...selected.value].filter((path) => available.has(path)))
  })
  onBeforeUnmount(() => clearTimeout(toastTimer))

  return {
    status,
    source,
    albums,
    albumTree,
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
    initialize,
    navigate,
    rescan,
    select,
    selectAll,
    clearSelection,
    mutate,
    createAlbum,
    notify,
    showDuplicates,
  }
}
