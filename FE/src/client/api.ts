import type { Action, ChatState, ChatSummary, ScheduleItem, SessionInfo, User } from '../shared/types.js';

export interface Meta {
  workplaces: { id: string; name: string; lat: number; lng: number }[];
  visitSlots: { id: string; label: string }[];
  dongs: { id: string; name: string; gu: string; lat: number; lng: number }[];
  stations: { name: string; lines: string; lat: number; lng: number }[];
}

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

const TIMEOUT_MS = 15000;

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), TIMEOUT_MS);
  let res: Response;
  try {
    res = await fetch(url, {
      method,
      credentials: 'same-origin',
      headers: body !== undefined || method === 'POST' ? { 'Content-Type': 'application/json' } : {},
      body: body !== undefined ? JSON.stringify(body) : method === 'POST' ? '{}' : undefined,
      signal: ctrl.signal,
    });
  } catch {
    throw new ApiError(0, 'network', '서버에 연결하지 못했어요. 인터넷 연결을 확인해 주세요.');
  } finally {
    clearTimeout(timer);
  }
  if (res.status === 204) return undefined as T;
  const data = (await res.json().catch(() => null)) as { error?: string; message?: string } | null;
  if (!res.ok) {
    throw new ApiError(
      res.status,
      data?.error ?? 'error',
      data?.message ?? '잠시 문제가 생겼어요. 다시 시도해 주세요.',
    );
  }
  return data as T;
}

export const api = {
  session: () => request<SessionInfo>('GET', '/api/session'),
  meta: () => request<Meta>('GET', '/api/meta'),
  mockLogin: () => request<{ user: User }>('POST', '/api/auth/mock-login'),
  guest: () => request<{ user: User }>('POST', '/api/auth/guest'),
  logout: () => request<{ ok: boolean }>('POST', '/api/auth/logout'),
  chats: () => request<{ chats: ChatSummary[] }>('GET', '/api/chats'),
  newChat: () => request<ChatState>('POST', '/api/chats'),
  chat: (id: string, rev?: number) =>
    request<ChatState | undefined>('GET', `/api/chats/${encodeURIComponent(id)}${rev ? `?rev=${rev}` : ''}`),
  deleteChat: (id: string) => request<{ ok: boolean }>('DELETE', `/api/chats/${encodeURIComponent(id)}`),
  send: (id: string, text: string) =>
    request<ChatState>('POST', `/api/chats/${encodeURIComponent(id)}/messages`, { text }),
  act: (id: string, action: Action) =>
    request<ChatState>('POST', `/api/chats/${encodeURIComponent(id)}/actions`, action),
  schedule: () => request<{ items: ScheduleItem[] }>('GET', '/api/schedule'),
  kakaoTalk: (on: boolean) => request<{ kakaoTalk: boolean }>('POST', '/api/notify/kakao', { on }),
  testNotify: () => request<{ ok: boolean }>('POST', '/api/notify/test'),
};
