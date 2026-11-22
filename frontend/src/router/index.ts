import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'
import DrillPreviewView from '@/views/DrillPreviewView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    // 下钻分析带专属透视预览工作台，需要在动态模块路由之前匹配
    { path: '/drill_down', name: 'drill_down', component: DrillPreviewView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
