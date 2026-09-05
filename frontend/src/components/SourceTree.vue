<script setup>
import { ref } from 'vue'
import Icon from './Icon.vue'
defineProps({
  nodes: { type: Array, default: () => [] },
  active: String,
  level: { type: Number, default: 0 },
})
defineEmits(['navigate'])
const collapsed = ref(new Set())
function toggle(path) {
  const next = new Set(collapsed.value)
  next.has(path) ? next.delete(path) : next.add(path)
  collapsed.value = next
}
</script>

<template>
  <ul class="source-tree">
    <li v-for="node in nodes" :key="node.path">
      <div class="tree-row" :class="{ active: active === node.path }" :style="{ '--level': level }">
        <button
          v-if="node.children.length"
          class="tree-expander"
          :aria-label="`${node.name} ${collapsed.has(node.path) ? 'aufklappen' : 'zuklappen'}`"
          :aria-expanded="!collapsed.has(node.path)"
          @click="toggle(node.path)"
        >
          <Icon :name="collapsed.has(node.path) ? 'chevron' : 'down'" :size="12" />
        </button>
        <span v-else class="tree-guide"></span>
        <button
          class="tree-link"
          :title="node.path"
          :aria-current="active === node.path ? 'page' : undefined"
          @click="$emit('navigate', node.path)"
        >
          <Icon :name="active === node.path ? 'folder-open' : 'folder'" :size="16" />
          <span>{{ node.name }}</span
          ><small>{{ node.count }}</small>
        </button>
      </div>
      <SourceTree
        v-if="node.children.length && !collapsed.has(node.path)"
        :nodes="node.children"
        :active="active"
        :level="level + 1"
        @navigate="$emit('navigate', $event)"
      />
    </li>
  </ul>
</template>
