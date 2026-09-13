import { createRouter, createWebHistory } from 'vue-router'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/meetings' },
    { path: '/meetings', component: () => import('@/views/MeetingListView.vue') },
    { path: '/meetings/new', component: () => import('@/views/MeetingCreateView.vue') },
    { path: '/meetings/:id/processing', component: () => import('@/views/ProcessingView.vue') },
    { path: '/meetings/:id', component: () => import('@/views/MeetingDetailView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/meetings' }
  ]
})
