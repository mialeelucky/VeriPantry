// Web push setup for an approver's device (frontend.md §4.4).

import { registerSW } from "virtual:pwa-register";
import { gatewayApi } from "../api/gateway";
import { b64urlToBytes } from "./jws";

let registration: Promise<ServiceWorkerRegistration | undefined> | null = null;

export function ensureServiceWorker(): Promise<ServiceWorkerRegistration | undefined> {
  if (!("serviceWorker" in navigator)) return Promise.resolve(undefined);
  if (!registration) {
    registration = new Promise((resolve) => {
      registerSW({ immediate: true, onRegisteredSW: (_url, reg) => resolve(reg), onRegisterError: () => resolve(undefined) });
    });
  }
  return registration;
}

export type PushSupport = "supported" | "insecure" | "unsupported" | "denied";

export function pushSupport(): PushSupport {
  if (!window.isSecureContext) return "insecure";
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) return "unsupported";
  if (Notification.permission === "denied") return "denied";
  return "supported";
}

/** Ask permission once, subscribe this device and register it with the gateway. */
export async function enablePush(token: string): Promise<{ devices: number }> {
  const permission = await Notification.requestPermission();
  if (permission !== "granted") throw new Error("Notifications were not allowed on this device.");
  const reg = await ensureServiceWorker();
  if (!reg) throw new Error("The app's service worker could not start.");
  const { publicKey } = await gatewayApi.pushKey();
  const existing = await reg.pushManager.getSubscription();
  const sub =
    existing ??
    (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64urlToBytes(publicKey) as BufferSource }));
  const r = await gatewayApi.subscribe(token, sub.toJSON());
  return { devices: r.devices };
}
