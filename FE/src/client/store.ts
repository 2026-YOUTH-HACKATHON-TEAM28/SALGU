/* 화면 상태와 서버 호출. 상태가 바뀌면 다음 프레임에 한 번만 다시 그려요. */
import type {
  Action,
  ChatState,
  ChatSummary,
  CondKey,
  ScheduleItem,
  SessionInfo,
  Stage,
} from '../shared/types.js';
import { maskPersonal } from '../shared/format.js';
import { api, ApiError, type Meta } from './api.js';

export type Panel = 'map' | 'sched' | null;
export type MobileTab = 'chat' | 'map' | 'sched';
export type MapMode = 'dong' | 'listing' | 'route';

export interface ConfirmOptions {
  title: string;
  body?: string;
  ok: string;
  cancel?: string;
  danger?: boolean;
}

export interface UiState {
  panel: Panel;
  mobileTab: MobileTab;
  accountOpen: boolean;
  listOpen: boolean;
  prefsExpanded: boolean;
  prefsForm: boolean;
  /** 조건 카드에서 '조건 n개 더 보기'를 펼쳤는지(카드 id) */
  condMore: Set<string>;
  /** 조건 카드의 고치기 양식을 연 카드 id */
  condEdit: string | null;
  /** 그 자리에서 고치는 조건 */
  inlineEdit: CondKey | null;
  /** 통화 카드에서 펼친 통화 id */
  openCalls: Set<string>;
  /** 펼친 매물 확인 상세 */
  openChecks: Set<string>;
  mapMode: MapMode;
  mapFocus: string | null;
  mapLayers: { stations: boolean; commuteRange: boolean };
  sheetOpen: boolean;
  mapDot: boolean;
  toast: { text: string; tone: 'info' | 'error' } | null;
  /** 화면 안 확인 창(브라우저 confirm 대신) */
  confirm: ConfirmOptions | null;
}

export interface AppState {
  boot: 'loading' | 'ready' | 'error';
  session: SessionInfo | null;
  meta: Meta | null;
  chats: ChatSummary[];
  chat: ChatState | null;
  pending: boolean;
  queue: string[];
  schedule: ScheduleItem[];
  ui: UiState;
}

type Listener = () => void;

export const state: AppState = {
  boot: 'loading',
  session: null,
  meta: null,
  chats: [],
  chat: null,
  pending: false,
  queue: [],
  schedule: [],
  ui: {
    panel: null,
    mobileTab: 'chat',
    accountOpen: false,
    listOpen: false,
    prefsExpanded: false,
    prefsForm: false,
    condMore: new Set(),
    condEdit: null,
    inlineEdit: null,
    openCalls: new Set(),
    openChecks: new Set(),
    mapMode: 'dong',
    mapFocus: null,
    mapLayers: { stations: true, commuteRange: false },
    sheetOpen: false,
    mapDot: false,
    toast: null,
    confirm: null,
  },
};

const listeners = new Set<Listener>();
let frame = 0;

export function subscribe(fn: Listener): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function update(fn?: (s: AppState) => void): void {
  fn?.(state);
  if (frame) return;
  frame = requestAnimationFrame(() => {
    frame = 0;
    for (const l of listeners) l();
  });
}

export function ui(patch: Partial<UiState>): void {
  update((s) => Object.assign(s.ui, patch));
}

let toastTimer = 0;
export function toast(text: string, tone: 'info' | 'error' = 'info'): void {
  window.clearTimeout(toastTimer);
  ui({ toast: { text, tone } });
  toastTimer = window.setTimeout(() => ui({ toast: null }), 4000);
}

function fail(err: unknown): void {
  if (err instanceof ApiError && err.status === 401) {
    update((s) => {
      if (s.session) s.session.user = null;
      s.chat = null;
    });
  }
  toast(err instanceof Error ? err.message : '잠시 문제가 생겼어요.', 'error');
}

/* ---------- 확인 창 ---------- */

let confirmResolve: ((ok: boolean) => void) | null = null;

/** 화면 안 확인 창을 띄우고, 누른 버튼을 돌려줘요(취소·Esc·바깥 누르기는 false) */
export function askConfirm(opts: ConfirmOptions): Promise<boolean> {
  confirmResolve?.(false);
  return new Promise((resolve) => {
    confirmResolve = resolve;
    ui({ confirm: opts });
  });
}

export function closeConfirm(ok: boolean): void {
  const r = confirmResolve;
  confirmResolve = null;
  ui({ confirm: null });
  r?.(ok);
}

/* ---------- 시작 · 로그인 ---------- */

export async function boot(): Promise<void> {
  try {
    const [session, meta] = await Promise.all([api.session(), api.meta()]);
    update((s) => {
      s.session = session;
      s.meta = meta;
    });
    if (session.user) await openLatest();
    update((s) => {
      s.boot = 'ready';
    });
    // BE 카카오 로그인에서 돌아온 결과(?loginError=true)를 알려 주고 주소는 깨끗이 해요.
    const q = new URLSearchParams(location.search);
    if (q.has('loginError')) {
      toast('카카오 로그인을 마치지 못했어요. 다시 시도해 주세요.', 'error');
      history.replaceState(null, '', location.pathname);
    }
  } catch (err) {
    update((s) => {
      s.boot = 'error';
    });
    fail(err);
  }
}

export async function login(kind: 'mock' | 'guest'): Promise<void> {
  if (kind === 'mock' && state.session?.kakaoLogin) {
    // BE 가 연결돼 있으면 진짜 카카오 로그인으로 보내요(돌아오면 /api/session 이 계정을 이어요).
    location.assign('/oauth2/authorization/kakao');
    return;
  }
  try {
    const { user } = kind === 'mock' ? await api.mockLogin() : await api.guest();
    const session = await api.session();
    update((s) => {
      s.session = { ...session, user };
    });
    await openLatest();
  } catch (err) {
    fail(err);
  }
}

export async function logout(): Promise<void> {
  try {
    await api.logout();
  } finally {
    stopPolling();
    update((s) => {
      if (s.session) s.session.user = null;
      s.chat = null;
      s.chats = [];
      s.schedule = [];
      s.ui.accountOpen = false;
      s.ui.panel = null;
    });
  }
}

async function openLatest(): Promise<void> {
  const { chats } = await api.chats();
  update((s) => {
    s.chats = chats;
  });
  if (chats[0]) await openChat(chats[0].id);
  else await newChat();
  void loadSchedule();
}

/* ---------- 대화 ---------- */

export async function refreshList(): Promise<void> {
  const { chats } = await api.chats();
  update((s) => {
    s.chats = chats;
  });
}

export async function openChat(id: string): Promise<void> {
  try {
    const chat = await api.chat(id);
    if (!chat) return;
    setChat(chat);
    update((s) => {
      s.ui.listOpen = false;
      s.ui.mobileTab = 'chat';
      s.ui.condEdit = null;
      s.ui.inlineEdit = null;
    });
  } catch (err) {
    fail(err);
  }
}

export async function newChat(): Promise<void> {
  try {
    // 지금 대화가 비어 있으면 그대로 써요.
    if (state.chat && state.chat.messages.length === 0) {
      ui({ mobileTab: 'chat', listOpen: false });
      return;
    }
    const chat = await api.newChat();
    setChat(chat);
    update((s) => {
      s.ui.mobileTab = 'chat';
      s.ui.listOpen = false;
    });
    await refreshList();
  } catch (err) {
    fail(err);
  }
}

export async function deleteChat(id: string): Promise<void> {
  try {
    await api.deleteChat(id);
    await refreshList();
    if (state.chat?.id === id) {
      if (state.chats[0]) await openChat(state.chats[0].id);
      else {
        update((s) => {
          s.chat = null;
        });
        await newChat();
      }
    }
    void loadSchedule();
  } catch (err) {
    fail(err);
  }
}

function setChat(chat: ChatState): void {
  const prev = state.chat;
  update((s) => {
    s.chat = chat;
    if (prev?.id === chat.id && prev.search !== chat.search && chat.search) s.ui.mapDot = true;
    // 통화 중인 곳은 자동으로 펼쳐요(사용자가 펼친 것은 그대로).
    for (const c of chat.batch?.calls ?? []) {
      if (c.status === 'in_progress') s.ui.openCalls.add(c.id);
    }
  });
  syncPolling();
}

/** 말 보내기. 답하는 중이면 앞 답변이 끝난 뒤 보내요. */
export async function send(raw: string): Promise<void> {
  const text = maskPersonal(raw.trim());
  if (!text) return;
  if (text !== raw.trim()) toast('개인정보로 보이는 숫자는 가리고 보냈어요.');
  if (state.pending) {
    update((s) => {
      s.queue.push(text);
    });
    return;
  }
  const chat = state.chat;
  if (!chat) return;
  update((s) => {
    s.pending = true;
    s.ui.mobileTab = 'chat';
    // 보내는 즉시 내 말풍선을 보여 줘요.
    s.chat?.messages.push({
      id: `local-${Date.now()}`,
      role: 'user',
      text,
      cards: [],
      chips: [],
      sources: [],
      at: new Date().toISOString(),
    });
  });
  try {
    setChat(await api.send(chat.id, text));
    void refreshList();
  } catch (err) {
    update((s) => {
      if (s.chat) s.chat.messages = s.chat.messages.filter((m) => !m.id.startsWith('local-'));
    });
    fail(err);
  } finally {
    update((s) => {
      s.pending = false;
    });
    const next = state.queue.shift();
    if (next) void send(next);
  }
}

export async function act(action: Action): Promise<boolean> {
  const chat = state.chat;
  if (!chat) return false;
  if (state.pending) {
    toast('앞 답변이 끝난 뒤에 눌러 주세요.');
    return false;
  }
  update((s) => {
    s.pending = true;
  });
  try {
    setChat(await api.act(chat.id, action));
    if (
      action.type === 'cancelVisit' ||
      action.type === 'acceptProposal' ||
      action.type === 'requestChange'
    ) {
      void loadSchedule();
    }
    return true;
  } catch (err) {
    fail(err);
    return false;
  } finally {
    update((s) => {
      s.pending = false;
    });
    const next = state.queue.shift();
    if (next) void send(next);
  }
}

/* ---------- 진행 확인(통화·확정 전화) ---------- */

let pollTimer = 0;
let pollFails = 0;

function stopPolling(): void {
  window.clearTimeout(pollTimer);
  pollTimer = 0;
}

function syncPolling(): void {
  if (state.chat?.live) {
    if (!pollTimer) schedulePoll(2500);
  } else stopPolling();
}

function schedulePoll(ms: number): void {
  window.clearTimeout(pollTimer);
  pollTimer = window.setTimeout(() => void poll(), ms);
}

async function poll(): Promise<void> {
  pollTimer = 0;
  const chat = state.chat;
  if (!chat?.live) return;
  if (document.hidden) {
    schedulePoll(5000);
    return;
  }
  try {
    const next = await api.chat(chat.id, chat.rev);
    pollFails = 0;
    if (next && state.chat?.id === next.id) {
      const wasLive = state.chat.live;
      setChat(next);
      if (wasLive && !next.live) void loadSchedule();
    }
  } catch {
    pollFails += 1;
  }
  if (state.chat?.live) schedulePoll(pollFails ? Math.min(30000, 2500 * 2 ** pollFails) : 2500);
}

document.addEventListener('visibilitychange', () => {
  if (!document.hidden && state.chat?.live) schedulePoll(100);
});

/* ---------- 일정 · 알림 ---------- */

/** 일정 탭의 버튼: 다른 대화의 방문일 수도 있어서 대화 id를 함께 보내요. */
export async function actOn(chatId: string, action: Action): Promise<void> {
  try {
    const next = await api.act(chatId, action);
    if (state.chat?.id === chatId) setChat(next);
    await loadSchedule();
  } catch (err) {
    fail(err);
  }
}

export async function loadSchedule(): Promise<void> {
  if (!state.session?.user) return;
  try {
    const { items } = await api.schedule();
    update((s) => {
      s.schedule = items;
    });
    notifyDue();
  } catch {
    /* 일정은 다음에 다시 불러와요 */
  }
}

export async function setKakaoTalk(on: boolean): Promise<void> {
  try {
    const r = await api.kakaoTalk(on);
    update((s) => {
      if (s.session) s.session.kakaoTalk = r.kakaoTalk;
    });
    toast(on ? '카카오톡 알림을 시험 연결했어요.' : '카카오톡 알림 연결을 끊었어요.');
  } catch (err) {
    fail(err);
  }
}

export async function testNotify(): Promise<void> {
  try {
    await api.testNotify();
    toast('시험 알림을 보냈어요. 지금은 시험 연결이라 실제 카카오톡으로는 가지 않아요.');
  } catch (err) {
    fail(err);
  }
}

/** 화면 알림: 이 화면이 열려 있으면 방문 전날 저녁(20시 이후)과 1시간 전에 한 번씩 알려요. */
function notifyDue(): void {
  const now = Date.now();
  for (const it of state.schedule) {
    const at = new Date(it.visit.at).getTime();
    const hourBefore = at - now <= 60 * 60000 && at > now;
    const eve = new Date(at - 86400000);
    eve.setHours(20, 0, 0, 0);
    const dayBefore = now >= eve.getTime() && at - now > 60 * 60000;
    const kind = hourBefore ? 'hour' : dayBefore ? 'day' : null;
    if (!kind) continue;
    const key = `salgu.notified.${it.visit.id}.${kind}`;
    try {
      if (localStorage.getItem(key)) continue;
      localStorage.setItem(key, '1');
    } catch {
      /* 저장이 막힌 브라우저에서도 알림은 보여요 */
    }
    const when = kind === 'hour' ? '1시간 뒤' : '내일';
    toast(`${when} ${it.listing.building} 방문이 있어요. ${it.broker?.name ?? ''}`);
    break;
  }
}
window.setInterval(notifyDue, 60000);

/* ---------- 이동 ---------- */

/** 헤더의 일정·지도 버튼: 이미 보이고 있으면 닫고, 아니면 열어요 */
export function togglePanel(panel: Exclude<Panel, null>): void {
  const mobile = window.matchMedia('(max-width: 767px)').matches;
  const open = mobile ? state.ui.mobileTab === panel : state.ui.panel === panel;
  if (open) {
    if (mobile) ui({ mobileTab: 'chat' });
    else ui({ panel: null });
    return;
  }
  openPanel(panel);
}

export function openPanel(
  panel: Exclude<Panel, null>,
  opts: { mode?: MapMode; focus?: string | null } = {},
): void {
  update((s) => {
    const mobile = window.matchMedia('(max-width: 767px)').matches;
    if (mobile) s.ui.mobileTab = panel === 'map' ? 'map' : 'sched';
    else s.ui.panel = panel;
    if (panel === 'map') {
      s.ui.mapDot = false;
      if (opts.mode) s.ui.mapMode = opts.mode;
      if (opts.focus !== undefined) s.ui.mapFocus = opts.focus;
      s.ui.sheetOpen = Boolean(opts.focus);
    }
  });
  if (panel === 'sched') void loadSchedule();
}

export function cardStage(kind: string): Stage | null {
  switch (kind) {
    case 'cond':
    case 'condForm':
      return 'cond';
    case 'dongs':
    case 'noMatch':
    case 'recs':
      return 'dong';
    case 'callPrep':
    case 'calls':
      return 'call';
    case 'rooms':
      return 'pick';
    case 'plan':
    case 'final':
      return 'meet';
    default:
      return null;
  }
}
