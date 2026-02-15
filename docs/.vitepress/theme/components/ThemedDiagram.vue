<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useData, withBase } from 'vitepress'

const props = defineProps({
  light: { type: String, required: true },
  dark: { type: String, required: true },
  alt: { type: String, default: '' }
})

const { isDark } = useData()

const dark = ref(!!isDark?.value)
let observer

function readDarkFromDom() {
  if (typeof document === 'undefined') return
  dark.value = document.documentElement.classList.contains('dark')
}

onMounted(() => {
  readDarkFromDom()
  observer = new MutationObserver(readDarkFromDom)
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
})

onBeforeUnmount(() => {
  if (observer) observer.disconnect()
})

const src = computed(() => withBase(dark.value ? props.dark : props.light))
</script>

<template>
  <img class="tutorial-diagram" :key="src" :src="src" :alt="alt" loading="lazy" decoding="async" />
</template>

<style scoped>
.tutorial-diagram {
  width: 100%;
  height: auto;
  display: block;
  border-radius: 10px;
}
</style>
