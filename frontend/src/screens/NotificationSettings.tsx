// Turn approval notifications on for this device (frontend.md §4.4).

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { BellRing, Smartphone, Webhook } from "lucide-react";
import { gatewayApi } from "../api/gateway";
import { useSession } from "../auth/session";
import { Button, Notice } from "../components/ui";
import { problemMessage } from "../lib/problems";
import { enablePush, pushSupport } from "../lib/push";

export default function NotificationSettings() {
  const { token, person } = useSession();
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me", token], queryFn: () => gatewayApi.me(token!), enabled: !!token });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ tone: "ok" | "stop"; text: string } | null>(null);
  const support = pushSupport();

  async function enable() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await enablePush(token!);
      setMsg({ tone: "ok", text: `Notifications are on. ${r.devices} device${r.devices > 1 ? "s" : ""} will be told about new requests.` });
      qc.invalidateQueries({ queryKey: ["me"] });
    } catch (e) {
      setMsg({ tone: "stop", text: e instanceof Error && !("code" in e) ? e.message : problemMessage(e) });
    } finally {
      setBusy(false);
    }
  }

  const channels = me.data?.channels;
  return (
    <div className="vp-step mx-auto w-full max-w-[420px]">
      <h1 className="text-[22px] font-medium">Notifications</h1>
      <p className="mt-1 text-ink-2">
        Requests that need {person?.displayName ?? "you"} come to this device, with a reminder an hour before they expire.
      </p>

      <div className="mt-5 space-y-2.5">
        <div className="flex items-center justify-between rounded-[14px] border border-line bg-surface p-4">
          <span className="flex items-center gap-3">
            <Smartphone className="size-5 text-ink-2" aria-hidden />
            <span>
              <span className="block font-medium">This device</span>
              <span className="block text-[13px] text-ink-2">{channels?.webPush ? `${channels.webPush} device(s) registered` : "Not registered yet"}</span>
            </span>
          </span>
        </div>
        <div className="flex items-center justify-between rounded-[14px] border border-line bg-surface p-4">
          <span className="flex items-center gap-3">
            <Webhook className="size-5 text-ink-2" aria-hidden />
            <span>
              <span className="block font-medium">Team channel</span>
              <span className="block text-[13px] text-ink-2">{channels?.webhook ? "Your organisation's webhook is set up" : "Not set up by your organisation"}</span>
            </span>
          </span>
        </div>
      </div>

      {support === "insecure" && (
        <div className="mt-4">
          <Notice tone="attention">Notifications need a secure (https) address. Open the app from its https link, or from localhost on this computer.</Notice>
        </div>
      )}
      {support === "unsupported" && (
        <div className="mt-4">
          <Notice tone="attention">This browser can't receive notifications. On iPhone, add the app to the home screen first (iOS 16.4 or later).</Notice>
        </div>
      )}
      {support === "denied" && (
        <div className="mt-4">
          <Notice tone="stop">Notifications are blocked for this site. Allow them in the browser's site settings.</Notice>
        </div>
      )}
      {me.data && !me.data.pushAvailable && (
        <div className="mt-4">
          <Notice tone="neutral">Push isn't configured on the server. The inbox still updates every few seconds.</Notice>
        </div>
      )}
      {msg && (
        <div className="mt-4">
          <Notice tone={msg.tone}>{msg.text}</Notice>
        </div>
      )}
      <Button variant="primary" className="mt-5 w-full" onClick={enable} busy={busy} disabled={support !== "supported" || !me.data?.pushAvailable}>
        <BellRing className="size-4" aria-hidden /> Turn on notifications
      </Button>
    </div>
  );
}
