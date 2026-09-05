<script setup>
defineProps({
  name: String,
  size: { type: [Number, String], default: 20 },
  stroke: { type: [Number, String], default: 1.7 },
})
const paths = {
  inbox: ['M4 4h16l2 11v5H2v-5L4 4Z', 'M2 15h6l2 3h4l2-3h6'],
  folder: ['M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V7Z'],
  'folder-open': ['M3 10V5h6l2 3h10v3', 'M3 10h19l-3 10H3V10Z'],
  images: ['M6 3h14a1 1 0 0 1 1 1v14', 'M3 7h14v14H3V7Z', 'm3 17 4-4 4 4 3-2 3 3', 'M12 11h.01'],
  grid: ['M3 3h7v7H3z', 'M14 3h7v7h-7z', 'M3 14h7v7H3z', 'M14 14h7v7h-7z'],
  list: ['M8 5h13M8 12h13M8 19h13', 'M3 5h.01M3 12h.01M3 19h.01'],
  search: ['M21 21l-5-5'],
  undo: ['M9 4 3 10l6 6', 'M3 10h12a6 6 0 0 1 0 12h-2'],
  refresh: ['M20 7V3l-3 3a8 8 0 0 0-13 5', 'M4 17v4l3-3a8 8 0 0 0 13-5', 'M20 3v5h-5', 'M4 21v-5h5'],
  chevron: ['m9 5 7 7-7 7'],
  down: ['m6 9 6 6 6-6'],
  arrow: ['M4 12h16', 'm14 6 6 6-6 6'],
  plus: ['M12 5v14M5 12h14'],
  check: ['m5 12 4 4L19 6'],
  minus: ['M5 12h14'],
  close: ['m6 6 12 12M6 18 18 6'],
  trash: ['M3 6h18', 'M9 6V3h6v3', 'm5 6 1 15h12l1-15', 'M10 10v7M14 10v7'],
  copy: ['M8 8h13v13H8z', 'M16 8V3H3v13h5'],
  shield: ['m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z', 'm8 12 3 3 5-6'],
  lock: ['M6 10h12v11H6z', 'M8 10V6a4 4 0 0 1 8 0v4', 'M12 15v2'],
  settings: [
    'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8',
    'm9 3-1 3-3 1-2 3 2 3v4l4 1 3 3 3-3 4-1v-4l2-3-2-3-3-1-1-3H9Z',
  ],
  clock: ['M12 7v5l3 2'],
  terminal: ['m4 7 5 5-5 5', 'M13 17h7'],
  keyboard: ['M2 5h20v14H2z', 'M6 9h.01M10 9h.01M14 9h.01M18 9h.01M6 13h.01M18 13h.01M9 15h6'],
  info: ['M12 11v6M12 7h.01'],
  expand: ['M8 3H3v5M16 3h5v5M3 16v5h5M21 16v5h-5'],
  sparkle: ['m12 2 2.8 7.2L22 12l-7.2 2.8L12 22l-2.8-7.2L2 12l7.2-2.8L12 2Z'],
  sun: ['M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M5 19l1.5-1.5M17.5 6.5 19 5'],
  mountain: ['m2 20 7-15 5 10 3-6 5 11H2Z', 'm6 11 3 2 3-2'],
  heart: [
    'M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z',
  ],
  plane: ['m22 2-7 20-4-9-9-4 20-7Z', 'm22 2-11 11'],
  building: ['M5 21V3h14v18M2 21h20M9 7h1M14 7h1M9 11h1M14 11h1M9 15h1M14 15h1M10 21v-3h4v3'],
  camera: ['M3 6h5l2-3h4l2 3h5v15H3V6Z'],
  laptop: ['M5 3h14v13H5z', 'm5 16-3 5h20l-3-5'],
  warning: ['m12 3 10 18H2L12 3Z', 'M12 9v5M12 17h.01'],
  menu: ['M4 6h16M4 12h16M4 18h16'],
}
const circles = {
  search: [10.5, 10.5, 6.5],
  clock: [12, 12, 9],
  info: [12, 12, 9],
  sun: [12, 12, 4],
  camera: [12, 13, 4],
}
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    :stroke-width="stroke"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    <path v-for="(d, i) in paths[name] || paths.folder" :key="i" :d="d" />
    <circle v-if="circles[name]" :cx="circles[name][0]" :cy="circles[name][1]" :r="circles[name][2]" />
  </svg>
</template>
