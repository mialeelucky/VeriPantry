// Fetch wrapper: JSON in, JSON out, RFC 9457 problems become ApiProblem.

export const GATEWAY_URL = (import.meta.env.VITE_GATEWAY_URL as string) ?? "http://127.0.0.1:8000";
export const AGENT_URL = (import.meta.env.VITE_AGENT_URL as string) ?? "http://127.0.0.1:8100";

export class ApiProblem extends Error {
  status: number;
  code: string;
  title: string;
  detail?: string;
  extra: Record<string, unknown>;

  constructor(status: number, body: Record<string, any>) {
    super(body.title ?? `Request failed (${status})`);
    this.status = status;
    this.title = body.title ?? `Request failed (${status})`;
    this.detail = body.detail;
    // ".../problems/insufficient-role" -> "insufficient-role"
    this.code = typeof body.type === "string" ? body.type.split("/").pop()! : `http-${status}`;
    this.extra = body;
  }
}

interface Options {
  method?: "GET" | "POST" | "DELETE";
  body?: unknown;
  token?: string | null;
}

export async function request<T>(base: string, path: string, { method = "GET", body, token }: Options = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;
  let res: Response;
  try {
    res = await fetch(base + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch {
    throw new ApiProblem(0, { title: "Can't reach the server", type: "network-unreachable" });
  }
  if (!res.ok) {
    let problem: Record<string, any> = { title: `Request failed (${res.status})` };
    try {
      problem = await res.json();
    } catch {
      /* not JSON */
    }
    throw new ApiProblem(res.status, problem);
  }
  return (await res.json()) as T;
}

export async function download(base: string, path: string, token: string | null, fallbackName: string): Promise<void> {
  const res = await fetch(base + path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) {
    let problem: Record<string, any> = {};
    try {
      problem = await res.json();
    } catch {
      /* ignore */
    }
    throw new ApiProblem(res.status, problem);
  }
  const blob = await res.blob();
  const match = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "");
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = match?.[1] ?? fallbackName;
  a.click();
  URL.revokeObjectURL(url);
}
