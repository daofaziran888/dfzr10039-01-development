import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import MissingRecrawlView from '@/views/MissingRecrawlView.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    { path: '/missing_recrawl', name: 'missing_recrawl', component: MissingRecrawlView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
