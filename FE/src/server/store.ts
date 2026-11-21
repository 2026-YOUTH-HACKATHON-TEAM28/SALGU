/* mock 저장소: 메모리에 두고 파일(JSON)로 주기적으로 저장해요. 실서비스에서는 BE(MySQL)가 맡아요. */
import { mkdirSync, readFileSync, renameSync, writeFileSync, existsSync } from 'node:fs';
import { join } from 'node:path';
import { randomBytes } from 'node:crypto';
import type { ChatState, User } from '../shared/types.js';
import type { SimInternal } from './mock/sim.js';

export interface UserRecord extends User {
  createdAt: string;
  kakaoTalk: boolean;
  calls: { date: string; count: number };
  /** BE users.id (카카오 로그인 후 BE /api/me 의 id) */
  beUserId?: number;
}

export interface SessionRecord {
  userId: string;
  createdAt: number;
  lastSeen: number;
}

export interface ChatRecord {
  userId: string;
  state: ChatState;
  internal: SimInternal;
}

interface DB {
  users: Record<string, UserRecord>;
  sessions: Record<string, SessionRecord>;
  chats: Record<string, ChatRecord>;
}

export const LIMITS = {
  chatsPerUser: 50,
  messagesPerChat: 400,
  callsPerDay: 10,
  sessionDays: 30,
};

export function newId(prefix: string): string {
  return `${prefix}_${randomBytes(9).toString('base64url')}`;
}

export class Store {
  private db: DB = { users: {}, sessions: {}, chats: {} };
  private dirty = false;
  private timer: NodeJS.Timeout | null = null;
  private readonly file: string;

  constructor(private readonly dir: string | null) {
    this.file = dir ? join(dir, 'store.json') : '';
    if (dir) {
      mkdirSync(dir, { recursive: true, mode: 0o700 });
      if (existsSync(this.file)) {
        try {
          this.db = JSON.parse(readFileSync(this.file, 'utf8')) as DB;
        } catch (err) {
          // 깨진 파일은 옆에 남기고 새로 시작해요.
          renameSync(this.file, `${this.file}.broken-${Date.now()}`);
          console.error('저장 파일을 읽지 못해 새로 시작해요', err);
        }
      }
      this.timer = setInterval(() => this.flush(), 1000);
      this.timer.unref();
    }
    this.pruneSessions();
  }

  markDirty(): void {
    this.dirty = true;
  }

  flush(): void {
    if (!this.dir || !this.dirty) return;
    this.dirty = false;
    const tmp = `${this.file}.tmp`;
    writeFileSync(tmp, JSON.stringify(this.db), { mode: 0o600 });
    renameSync(tmp, this.file);
  }

  close(): void {
    if (this.timer) clearInterval(this.timer);
    this.flush();
  }

  /* 사용자 · 세션 */

  createUser(kind: User['kind'], name: string): UserRecord {
    const user: UserRecord = {
      id: newId('u'),
      name,
      kind,
      photo: null,
      createdAt: new Date().toISOString(),
      kakaoTalk: false,
      calls: { date: '', count: 0 },
    };
    this.db.users[user.id] = user;
    this.markDirty();
    return user;
  }

  /** BE 사용자(users.id)와 이어진 화면 계정(없으면 만들어요) */
  userByBe(beUserId: number, name: string): UserRecord {
    const found = Object.values(this.db.users).find((u) => u.beUserId === beUserId);
    if (found) {
      if (name && found.name !== name) {
        found.name = name;
        this.markDirty();
      }
      return found;
    }
    const user = this.createUser('kakao', name || '카카오 사용자');
    user.beUserId = beUserId;
    this.markDirty();
    return user;
  }

  user(id: string): UserRecord | undefined {
    return this.db.users[id];
  }

  createSession(userId: string): string {
    const sid = randomBytes(32).toString('base64url');
    this.db.sessions[sid] = { userId, createdAt: Date.now(), lastSeen: Date.now() };
    this.markDirty();
    return sid;
  }

  session(sid: string | undefined): SessionRecord | undefined {
    if (!sid) return undefined;
    const s = this.db.sessions[sid];
    if (!s) return undefined;
    if (Date.now() - s.lastSeen > LIMITS.sessionDays * 86400000) {
      delete this.db.sessions[sid];
      this.markDirty();
      return undefined;
    }
    if (Date.now() - s.lastSeen > 60000) {
      s.lastSeen = Date.now();
      this.markDirty();
    }
    return s;
  }

  deleteSession(sid: string): void {
    delete this.db.sessions[sid];
    this.markDirty();
  }

  private pruneSessions(): void {
    const cut = Date.now() - LIMITS.sessionDays * 86400000;
    for (const [sid, s] of Object.entries(this.db.sessions))
      if (s.lastSeen < cut) delete this.db.sessions[sid];
  }

  /* 대화 */

  chatsOf(userId: string): ChatRecord[] {
    return Object.values(this.db.chats)
      .filter((c) => c.userId === userId)
      .sort((a, b) => b.state.updatedAt.localeCompare(a.state.updatedAt));
  }

  chat(id: string, userId: string): ChatRecord | undefined {
    const c = this.db.chats[id];
    return c && c.userId === userId ? c : undefined;
  }

  putChat(rec: ChatRecord): void {
    this.db.chats[rec.state.id] = rec;
    const mine = this.chatsOf(rec.userId);
    for (const old of mine.slice(LIMITS.chatsPerUser)) delete this.db.chats[old.state.id];
    this.markDirty();
  }

  deleteChat(id: string, userId: string): boolean {
    if (!this.chat(id, userId)) return false;
    delete this.db.chats[id];
    this.markDirty();
    return true;
  }

  /** 시험 전화 하루 3번 */

  /** 하루 통화 수 한도(10통) 확인 후 더하기 */
  useCalls(userId: string, n: number, today: string): number {
    const u = this.db.users[userId];
    if (!u) return 0;
    if (u.calls.date !== today) u.calls = { date: today, count: 0 };
    const allowed = Math.max(0, Math.min(n, LIMITS.callsPerDay - u.calls.count));
    u.calls.count += allowed;
    this.markDirty();
    return allowed;
  }
}
