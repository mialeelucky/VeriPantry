/// <reference lib="webworker" />
// Service worker: app shell caching, and approval notifications (frontend.md §4.4).
// A notification only carries a title, a short body and a link; never a token.

import { precacheAndRoute } from "workbox-precaching";

declare const self: ServiceWorkerGlobalScope & { __WB_MANIFEST: any };

precacheAndRoute(self.__WB_MANIFEST);
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

self.addEventListener("push", (event) => {
  let data: { title?: string; body?: string; url?: string; approvalId?: string; kind?: string } = {};
  try {
    data = event.data?.json() ?? {};
  } catch {
    data = { title: "VeriPantry", body: event.data?.text() };
  }
  event.waitUntil(
    self.registration.showNotification(data.title ?? "VeriPantry", {
      body: data.body,
      icon: "/icon.svg",
      badge: "/icon.svg",
      tag: data.approvalId, // a reminder or decided notice replaces the earlier one
      data: { url: data.url ?? "/approvals" },
      requireInteraction: data.kind === "request",
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const url = new URL(event.notification.data?.url ?? "/approvals", self.location.origin).href;
  event.waitUntil(
    (async () => {
      const windows = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
      const open = windows.find((w) => new URL(w.url).origin === self.location.origin);
      if (open) {
        await open.navigate(url);
        return open.focus();
      }
      return self.clients.openWindow(url);
    })(),
  );
});
