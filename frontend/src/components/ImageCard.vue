<script setup>
import { ref, watch } from 'vue'
import { imageUrl, formatSize } from '../api'
import Icon from './Icon.vue'
const props = defineProps({
  image: Object,
  selected: Boolean,
  selectable: { type: Boolean, default: true },
  index: Number,
  list: Boolean,
})
const emit = defineEmits(['select', 'preview'])
const failed = ref(false)
watch(
  () => props.image.path + props.image.modified_at,
  () => {
    failed.value = false
  },
)
function choose(event) {
  if (props.selectable) emit('select', event)
  else emit('preview')
}
</script>

<template>
  <article
    class="image-card"
    :class="{ selected, 'is-list': list }"
    @click="choose"
    @dblclick.stop="$emit('preview')"
  >
    <div class="image-visual">
      <img
        v-if="!failed"
        :src="imageUrl(image.path) + '?v=' + encodeURIComponent(image.modified_at)"
        :alt="image.name"
        :loading="index < 12 ? 'eager' : 'lazy'"
        decoding="async"
        draggable="false"
        @error="failed = true"
      />
      <div v-else class="image-fallback"><Icon name="images" :size="30" /><span>Keine Vorschau</span></div>
      <button
        v-if="selectable"
        class="image-checkbox"
        role="checkbox"
        :aria-checked="selected"
        :aria-label="`${image.name} auswählen`"
        @click.stop="$emit('select', $event)"
        @dblclick.stop
      >
        <Icon v-if="selected" name="check" :size="14" :stroke="2.5" />
      </button>
      <span
        v-if="image.is_duplicate"
        class="duplicate-badge"
        :title="`Bereits in ${image.duplicate_of.join(', ')}`"
        ><Icon name="copy" :size="11" /> Duplikat</span
      >
      <button
        class="image-expand"
        :aria-label="`${image.name} vergrößern`"
        @click.stop="$emit('preview')"
        @dblclick.stop
      >
        <Icon name="expand" :size="15" />
      </button>
      <span class="image-dimensions">{{
        image.width && image.height ? `${image.width} × ${image.height}` : image.format
      }}</span>
    </div>
    <div class="image-caption">
      <h3 :title="image.name">{{ image.name }}</h3>
      <div class="image-meta">
        <span>{{ formatSize(image.size) }}</span
        ><span class="file-type">{{ image.format }}</span>
      </div>
    </div>
    <Icon v-if="list && selected" class="list-check" name="check" :size="18" />
  </article>
</template>
