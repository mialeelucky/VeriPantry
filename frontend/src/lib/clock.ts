// Countdowns follow the gateway's clock, which decides expiry. With recorded
// supplier data the gateway runs on recorded time, so the browser's clock alone
// would show the wrong time left.

import { useQuery } from "@tanstack/react-query";
import { GATEWAY_URL, request } from "../api/client";

export function useGatewayOffset(): number {
  const q = useQuery({
    queryKey: ["gateway-clock"],
    queryFn: async () => {
      const sent = Date.now();
      const h = await request<{ now: string }>(GATEWAY_URL, "/health");
      const received = Date.now();
      return new Date(h.now).getTime() - (sent + received) / 2;
    },
    staleTime: 5 * 60_000,
  });
  return q.data ?? 0;
}
