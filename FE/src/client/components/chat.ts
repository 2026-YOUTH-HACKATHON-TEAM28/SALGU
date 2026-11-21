import { html, nothing, type TemplateResult } from 'lit-html';
import { repeat } from 'lit-html/directives/repeat.js';
import type { Message, Stage } from '../../shared/types.js';
import { NEXT_ACTION, STAGES } from '../../shared/labels.js';
import { icons, logo } from '../icons.js';
import { sources } from './common.js';
import { act, cardStage, openPanel, send, state, ui } from '../store.js';
import { renderCard } from './cards.js';
import { prefsView } from './prefs.js';

const EXAMPLES = [
  '여의도역으로 출근해요. 월세 60만 원 이하, 보증금 1000만 원이면 좋겠어요',
  '강남역 다니는데 월세 65까지, 번화한 동네가 좋아요',
  '고양이 키우는데 시청역 출근, 월세 60 이하로 찾아줘',
  '집 찾아줘 (하나씩 물어봐 줘)',
];
const MORE_EXAMPLES = [
  '환산월세가 뭐야?',
  '전입신고는 언제까지 해?',
  '전월세 전환율이 뭐야?',
  '청년 월세 지원 받을 수 있어?',
];

/** S-01 첫 화면 */
function homeView() {
  return html`<section class="home" aria-labelledby="home-title">
    <div class="home-logo">${logo(40)}</div>
    <h2 id="home-title">안녕하세요, <em>살구</em>예요.<br />어떤 집을 찾고 있어요?</h2>
    <p class="home-lead">
      회사가 어디고 월세를 얼마까지 낼 수 있는지 알려 주세요. 출퇴근하기 괜찮은 동네를 고르고, 그 동네
      중개사무소 몇 곳에 대신 전화해서 비슷한 집이 있는지 물어볼게요. 마음에 드는 방을 고르면 집 보러 갈
      시간까지 맞춰 드려요.
    </p>
    <button class="home-form" @click=${() => act({ type: 'openCondForm' })} data-testid="open-cond-form">
      <span>
        <strong>조건 골라서 찾기</strong>
        <span class="sub">회사, 월세, 출퇴근 시간을 칸에서 골라요</span>
      </span>
      <span class="chev" aria-hidden="true">›</span>
    </button>
    <p class="home-sub">아니면 이렇게 말해도 돼요</p>
    <ul class="examples">
      ${EXAMPLES.map(
        (e) =>
          html`<li>
            <button
              class="example"
              @click=${() => send(e.replace(' (하나씩 물어봐 줘)', ', 하나씩 물어봐 줘'))}
            >
              ${e}
            </button>
          </li>`,
      )}
    </ul>
    <details class="more-examples">
      <summary>다른 질문 예시</summary>
      <ul class="examples">
        ${MORE_EXAMPLES.map((e) => html`<li><button class="example" @click=${() => send(e)}>${e}</button></li>`)}
      </ul>
    </details>
  </section>`;
}

function chipClick(chip: string): void {
  if (chip === '일정 탭에서 보기' || chip === '일정 보여줘') openPanel('sched');
  else if (chip === '조건 골라서 찾기') void act({ type: 'openCondForm' });
  else if (chip === '이 조건으로 다시 찾기' || chip === '이대로 찾아줘') void act({ type: 'search' });
  else if (chip === '최종 추천 보여줘') void act({ type: 'showFinal' });
  else void send(chip);
}

/** 살구 답변 문구: 줄 앞에 '- '가 있으면 목록으로 */
function botText(text: string): TemplateResult {
  const blocks: TemplateResult[] = [];
  let list: string[] = [];
  const flush = () => {
    if (list.length)
      blocks.push(
        html`<ul>
          ${list.map((l) => html`<li>${l}</li>`)}
        </ul>`,
      );
    list = [];
  };
  for (const line of text.split('\n')) {
    if (line.startsWith('- ')) list.push(line.slice(2));
    else {
      flush();
      if (line.trim()) blocks.push(html`<p>${line}</p>`);
    }
  }
  flush();
  return html`<div class="bot-text">${blocks}</div>`;
}

function messageView(m: Message, last: boolean): TemplateResult {
  if (m.role === 'user') {
    return html`<div class="user-row" data-testid="msg-user"><div class="bubble user">${m.text}</div></div>`;
  }
  return html`<article class="bot-msg" data-testid="msg-bot">
    <header class="bot-name"><span class="avatar" aria-hidden="true">${logo(20)}</span>살구</header>
    ${m.text ? botText(m.text) : nothing}
    ${m.cards.map(
      (c) =>
        html`<div class="card-wrap" data-stage=${cardStage(c.kind) ?? ''} id=${`card-${c.id}`}>
          ${renderCard(c, m)}
        </div>`,
    )}
    ${
      last && m.chips.length
        ? html`<div class="chips" role="group" aria-label="이어서 할 말">
            ${m.chips.map(
              (c) =>
                html`<button class="chip" ?disabled=${state.pending} @click=${() => chipClick(c)}>
                  ${c}
                </button>`,
            )}
          </div>`
        : nothing
    }
    ${sources(m.sources)}
  </article>`;
}

/** 진행 단계 바: 끝난 단계(✓)를 누르면 그 카드로 */
function progressView(): TemplateResult | typeof nothing {
  const chat = state.chat;
  if (!chat || !chat.messages.length) return nothing;
  const cur = STAGES.findIndex((s) => s.id === chat.stage);
  const jump = (stage: Stage) => {
    const el = [...document.querySelectorAll<HTMLElement>(`.card-wrap[data-stage="${stage}"]`)].pop();
    const log = document.querySelector<HTMLElement>('.log');
    if (!el || !log) return;
    // scrollIntoView 는 페이지 자체까지 밀어 올릴 수 있어서 대화 칸만 움직여요.
    const top = log.scrollTop + el.getBoundingClientRect().top - log.getBoundingClientRect().top - 8;
    log.scrollTo({ top, behavior: 'smooth' });
  };
  const next =
    chat.stage === 'call' && !chat.batch
      ? '입주 희망일과 계약 기간을 골라 전화를 걸어 주세요'
      : NEXT_ACTION[chat.stage];
  return html`<nav class="progress" aria-label="진행 단계">
    <ol>
      ${STAGES.map((s, i) => {
        const done = i < cur;
        const now = i === cur;
        return html`<li class=${done ? 'done' : now ? 'now' : ''}>
          <button ?disabled=${!done} aria-current=${now ? 'step' : nothing} @click=${() => jump(s.id)}>
            <span class="step-no" aria-hidden="true">${done ? '✓' : i + 1}</span>${s.label}
          </button>
        </li>`;
      })}
    </ol>
    <p class="next">다음 할 일 · ${next}</p>
  </nav>`;
}

let lastCount = 0;
let lastChatId = '';
let wasNearBottom = true;

/** 다시 그리기 전에: 사용자가 맨 아래 근처를 보고 있었는지 */
export function beforeChatRender(): void {
  const log = document.querySelector<HTMLElement>('.log');
  wasNearBottom = !log || log.scrollHeight - log.scrollTop - log.clientHeight < 160;
}

/** 새 말이 생기면 새 답변의 처음이 보이게(사용자가 위를 보고 있었으면 그대로) */
export function afterChatRender(): void {
  const log = document.querySelector<HTMLElement>('.log');
  const chat = state.chat;
  if (!log || !chat) return;
  const count = chat.messages.length + (state.pending ? 1 : 0);
  if (chat.id !== lastChatId) {
    lastChatId = chat.id;
    lastCount = count;
    log.scrollTo({ top: log.scrollHeight, behavior: 'instant' });
    return;
  }
  if (count === lastCount) return;
  const grew = count > lastCount;
  lastCount = count;
  const last = chat.messages.at(-1);
  if (!grew || (!wasNearBottom && last?.role !== 'user')) return;
  if (state.pending || last?.role === 'user') {
    log.scrollTo({ top: log.scrollHeight, behavior: 'smooth' });
    return;
  }
  // 살구 답변: 새 답변의 머리가 보이게
  const rows = log.querySelectorAll<HTMLElement>('[data-testid="msg-bot"]');
  const target = rows[rows.length - 1];
  if (!target) return;
  const top = target.offsetTop - log.offsetTop - 12;
  log.scrollTo({ top, behavior: 'smooth' });
}

function composer() {
  const onSubmit = (e: Event) => {
    e.preventDefault();
    const form = e.currentTarget as HTMLFormElement;
    const input = form.elements.namedItem('msg') as HTMLTextAreaElement;
    const text = input.value;
    if (!text.trim()) return;
    input.value = '';
    void send(text);
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      (e.currentTarget as HTMLTextAreaElement).form?.requestSubmit();
    }
  };
  return html`<div class="composer-wrap">
    <form class="composer" @submit=${onSubmit}>
      <label class="sr-only" for="msg">살구에게 말하기</label>
      <textarea
        id="msg"
        name="msg"
        rows="1"
        maxlength="500"
        placeholder="예) 회사가 강남역이고 월세 60 이하, 역 가까운 집 찾아줘"
        @keydown=${onKey}
        data-testid="composer-input"
      ></textarea>
      <button class="send" type="submit" aria-label="보내기" data-testid="composer-send">
        ${icons.send()}
      </button>
    </form>
    <p class="composer-note">
      동네·시세·중개사무소는 실거래 DB 기준이에요. 실거래는 지난 계약이라 지금 나온 방은 전화로 확인해요. 시험
      중이라 실제로 전화하지는 않아요.
    </p>
  </div>`;
}

/** 대화 칸 바깥 여백에서 굴린 휠도 대화를 스크롤해요(대화 칸을 메시지 너비로 줄였기 때문) */
function forwardWheel(e: WheelEvent): void {
  const t = e.target as HTMLElement;
  if (t.closest('.log, textarea, .prefs-form, .drawer, .menu')) return;
  document.querySelector<HTMLElement>('.log')?.scrollBy({ top: e.deltaY });
}

export function chatView() {
  const chat = state.chat;
  const msgs = chat?.messages ?? [];
  return html`<section class="chat" aria-label="집 찾기 대화" @wheel=${forwardWheel}>
    ${progressView()}
    <div class="log" role="log" aria-live="polite" data-testid="chat-log">
      ${msgs.length ? nothing : homeView()}
      ${repeat(
        msgs,
        (m) => m.id,
        (m, i) => messageView(m, i === msgs.length - 1),
      )}
      ${
        state.pending
          ? html`<article class="bot-msg typing" aria-label="살구가 답을 정리하는 중">
              <header class="bot-name"><span class="avatar" aria-hidden="true">${logo(20)}</span>살구</header>
              <p class="typing-text">
                <span class="dots"><i></i><i></i><i></i></span>답을 정리하는 중
              </p>
            </article>`
          : nothing
      }
      ${
        state.queue.length
          ? html`<p class="queued">앞 답변이 끝나면 보낼게요: ${state.queue.join(' / ')}</p>`
          : nothing
      }
    </div>
    ${prefsView()} ${composer()}
  </section>`;
}

export function closeFloating(e: Event): void {
  const t = e.target as HTMLElement;
  if (state.ui.accountOpen && !t.closest('.account')) ui({ accountOpen: false });
  if (state.ui.listOpen && !t.closest('.drawer') && !t.closest('[data-testid="hdr-chats"]')) {
    ui({ listOpen: false });
  }
}
