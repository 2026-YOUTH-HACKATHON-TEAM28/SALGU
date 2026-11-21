import { html, nothing, type TemplateResult } from 'lit-html';
import type { Call, CallPrep, Card } from '../../../shared/types.js';
import { callLabel, isCallActive } from '../../../shared/labels.js';
import { dateTime, depRent, hm } from '../../../shared/format.js';
import { act, askPhone, state, toast, update } from '../../store.js';
import { badge, copyText } from '../common.js';
import { dongName, typeName } from './listing.js';

const MOVE_IN = ['바로', '12월 초', '12월 말', '1월 이후'];
const TERMS = ['1년', '2년'];

function inBusinessHours(d = new Date()): boolean {
  return d.getDay() !== 0 && d.getHours() >= 9 && d.getHours() < 19;
}

function seg<T extends string | boolean>(
  name: string,
  options: { v: T; label: string }[],
  current: T | null,
  onPick: (v: T) => void,
  required = false,
): TemplateResult {
  return html`<fieldset class="seg">
    <legend>${name}${required ? html`<em>필수</em>` : nothing}</legend>
    <div class="seg-btns">
      ${options.map(
        (o) =>
          html`<button
            type="button"
            class="seg-btn"
            aria-pressed=${current === o.v}
            ?disabled=${state.pending}
            @click=${() => onPick(o.v)}
          >
            ${o.label}
          </button>`,
      )}
    </div>
  </fieldset>`;
}

/** 통화 안내: 전화 에이전트 모드에 따라 */
function phoneNote(): string {
  const m = state.session?.phoneMode;
  if (m === 'demo' || m === 'live') return 'AI 실제 통화 · 실제 중개사무소 대신 입력하신 본인 번호로 걸려요.';
  if (m === 'mock') return 'AI 통화(전화 서버 시험 모드) · 실제로 전화를 걸지 않아요.';
  return 'AI 통화 시뮬레이션 · 실제로 전화를 걸지 않아요.';
}

/** S-04 전화 전 준비 */
export function callPrepCard(card: Extract<Card, { kind: 'callPrep' }>): TemplateResult {
  const chat = state.chat;
  const prep = chat?.prep;
  if (card.done || !prep) return html`<article class="card folded">전화 준비를 마쳤어요.</article>`;
  const set = (patch: Partial<CallPrep>) => act({ type: 'updatePrep', patch });
  const dongs = chat?.search?.dongs.filter((d) => prep.dongIds.includes(d.id)) ?? [];
  const ready = Boolean(prep.moveIn && prep.term);
  const share = prep.share;
  const rent = chat?.conditions.rent?.value;
  const perDong = Math.max(1, state.session?.brokersPerDong ?? 1);
  return html`<article class="card prep" data-testid="callprep-card">
    <header class="card-title">
      <h3>전화 전 준비</h3>
      <span class="sub"
        >동네마다 등록 중개사무소 ${perDong}곳 · 비슷한 방과 보여 줄 수 있는 시간을 물어요</span
      >
    </header>
    <section class="call-targets">
      ${dongs.map(
        (d) =>
          html`<div class="target">
            <strong>${d.name}</strong>
            <ul class="plain">
              ${d.brokers.map(
                (b, i) =>
                  html`<li class=${i < perDong ? 'to-call' : 'skip'} data-testid="prep-broker">
                    <span class="b-name">${b.name}</span>
                    <span class="b-phone">${b.phone}</span>
                    <span class="muted">등록 ${b.regNo}${i < perDong ? '' : ' · 이번엔 걸지 않아요'}</span>
                  </li>`,
              )}
            </ul>
          </div>`,
      )}
    </section>
    ${seg(
      '입주 희망일',
      MOVE_IN.map((v) => ({ v, label: v })),
      prep.moveIn,
      (v) => set({ moveIn: v }),
      true,
    )}
    ${seg(
      '계약 기간',
      TERMS.map((v) => ({ v, label: v })),
      prep.term,
      (v) => set({ term: v }),
      true,
    )}
    ${seg(
      '반려동물',
      [
        { v: true, label: '있어요' },
        { v: false, label: '없어요' },
      ],
      prep.pet,
      (v) => set({ pet: v }),
    )}
    ${seg(
      '방문 가능 시간',
      (state.meta?.visitSlots ?? []).map((s) => ({ v: s.id, label: s.label })),
      prep.visitSlot,
      (v) => set({ visitSlot: v }),
    )}
    <fieldset class="seg">
      <legend>중개사에게 알려줄 정보</legend>
      <div class="checks">
        ${(
          [
            ['condition', '희망 조건'],
            ['slot', '방문 가능 시간'],
            ['surname', '성(○○)'],
            ['contact', '내 연락처'],
          ] as const
        ).map(
          ([k, label]) =>
            html`<label
              ><input
                type="checkbox"
                .checked=${share[k]}
                ?disabled=${state.pending}
                @change=${(e: Event) => set({ share: { ...share, [k]: (e.target as HTMLInputElement).checked } })}
              />
              ${label}</label
            >`,
        )}
      </div>
      <p class="note">체크한 것만 말해요. 계약, 가계약금, 가격 합의는 하지 않아요.</p>
    </fieldset>
    <details class="script">
      <summary>통화 대본 미리 보기</summary>
      <ol>
        <li>
          안녕하세요, 저는 살구의 AI 비서예요. 집을 구하는 분을 대신해 전화드렸어요. 원하지 않으시면 말씀해
          주세요.
        </li>
        <li>
          ${share.condition ? `근처에 월세 ${rent ?? '○○'}만 원 이하 방이 있을까요?` : '근처에 원룸이 있을까요?'}
          ${prep.moveIn ? ` 입주는 ${prep.moveIn}이에요.` : ''}${prep.term ? ` 계약은 ${prep.term} 생각해요.` : ''}
        </li>
        ${share.slot && prep.visitSlot ? html`<li>보여 주실 수 있는 시간이 언제일까요?</li>` : nothing}
      </ol>
    </details>
    ${
      inBusinessHours()
        ? nothing
        : html`<p class="hours">지금은 영업시간(월~토 9~19시)이 아니에요. 전화는 다음 영업 시작에 걸려요.</p>`
    }
    <div class="card-foot">
      <button
        class="btn-primary"
        ?disabled=${!ready || state.pending}
        @click=${startCalls}
        data-testid="start-calls"
      >
        이대로 전화하기
      </button>
      <span class="note"
        >${ready ? '위 번호 대신 적어 주신 본인 번호로 걸어요(실제 중개사무소에는 연락하지 않아요)' : '입주 희망일과 계약 기간을 골라 주세요'}</span
      >
    </div>
  </article>`;
}

function callRow(c: Call): TemplateResult {
  const chat = state.chat!;
  const broker = chat.brokers.find((b) => b.id === c.brokerId);
  const label = callLabel(c.status, c.outcome);
  const live = isCallActive(c.status);
  const open = state.ui.openCalls.has(c.id);
  const listings = chat.listings.filter((l) => c.listingIds.includes(l.id));
  const toggle = () =>
    update((s) => {
      if (open) s.ui.openCalls.delete(c.id);
      else s.ui.openCalls.add(c.id);
    });
  return html`<li class="call-row" data-testid="call-row" data-status=${c.status}>
    <button class="call-main" aria-expanded=${open} @click=${toggle}>
      ${badge(label, { live, testid: 'call-status' })}
      <span class="call-name">${broker?.name ?? '중개사무소'}</span>
      <span class="call-found">
        ${c.status === 'retry_wait' && c.retryAt ? `${hm(c.retryAt)}에 다시 걸어요` : nothing}
        ${
          listings.length
            ? listings
                .map((l) => `${l.building} ${typeName(l.type)} ${l.area}㎡ · ${depRent(l.deposit, l.rent)}`)
                .join(', ')
            : nothing
        }
      </span>
      <span class="call-toggle">통화 내용 <span aria-hidden="true">${open ? '▴' : '▾'}</span></span>
    </button>
    ${
      open
        ? html`<div class="call-detail">
            <p class="muted">
              전화 ${broker?.phone ?? ''} · 등록번호
              ${broker?.regNo ?? ''}${c.attempts > 1 ? ` · ${c.attempts}번째 통화` : ''}
            </p>
            ${c.slots.length ? html`<p>보여 줄 수 있는 시간: ${c.slots.map(dateTime).join(', ')}</p>` : nothing}
            ${
              c.lines.length
                ? html`<ol class="lines">
                    ${c.lines.map(
                      (l) =>
                        html`<li class="line-${l.who}">
                          <span class="who"
                            >${l.who === 'agent' ? '살구' : l.who === 'broker' ? '중개사' : '시스템'}</span
                          >${l.text}
                        </li>`,
                    )}
                  </ol>`
                : html`<p class="muted">아직 통화 내용이 없어요.</p>`
            }
            ${
              c.smsDraft
                ? html`<div class="sms">
                    <p class="note">받지 않아서 문자 초안을 만들었어요. 살구가 대신 보내지 않아요.</p>
                    <p>${c.smsDraft}</p>
                    <button
                      class="btn-ghost small"
                      @click=${async () =>
                        toast(
                          (await copyText(c.smsDraft ?? ''))
                            ? '문자 초안을 복사했어요.'
                            : '복사하지 못했어요.',
                        )}
                    >
                      복사
                    </button>
                  </div>`
                : nothing
            }
          </div>`
        : nothing
    }
  </li>`;
}

/** S-05 AI 통화: 진행 요약과 동네별 한 줄, 줄을 누르면 통화 내용 */
export function callsCard(_card: Extract<Card, { kind: 'calls' }>): TemplateResult {
  const chat = state.chat;
  const batch = chat?.batch;
  if (!chat || !batch) return html`<article class="card folded">통화 기록이 없어요.</article>`;
  const calls = batch.calls;
  const done = calls.filter((c) => c.status === 'done').length;
  const found = calls.filter((c) => c.outcome === 'listing').length;
  const noAnswer = calls.filter((c) => c.outcome === 'no_answer' || c.status === 'retry_wait').length;
  const dongIds = [...new Set(calls.map((c) => c.dongId))];
  return html`<article class="card calls" data-testid="calls-card">
    <header class="card-title">
      <h3>중개사무소 통화 ${done}/${calls.length}</h3>
      <span class="sub"
        >${done === calls.length ? '모두 끝났어요' : '차례로 거는 중'} · 줄을 누르면 통화 내용을 볼 수
        있어요</span
      >
    </header>
    <div
      class="bar"
      role="progressbar"
      aria-valuemin="0"
      aria-valuemax=${calls.length}
      aria-valuenow=${done}
      aria-label="통화 진행"
    >
      <i style="width:${(done / Math.max(calls.length, 1)) * 100}%"></i>
    </div>
    <div class="pills">
      <span class="pill ok">방 있음 <b>${found}</b></span>
      <span class="pill">응답 없음 <b>${noAnswer}</b></span>
    </div>
    ${dongIds.map(
      (id) =>
        html`<section class="call-group">
          <h4>${dongName(id)}</h4>
          <ul class="plain">
            ${calls.filter((c) => c.dongId === id).map(callRow)}
          </ul>
        </section>`,
    )}
    <p class="foot-note">
      ${phoneNote()} 서울시 등록 중개사무소만 걸어요. 통화 첫마디에 AI임을 알리고, 같은 곳은 하루 1번만
      걸어요.
    </p>
  </article>`;
}

/** 이대로 전화하기: 아직 실제 중개사무소에는 연락하지 않아서, 본인 번호를 받아 그 번호로만 걸어요 */
async function startCalls(): Promise<void> {
  const phone = await askPhone({
    title: '본인 휴대폰 번호를 적어 주세요',
    body: '지금은 실제 중개사무소에 연락하지 않아요. 중개사무소에 물어볼 통화를 이 번호로 대신 걸어요. 중개사 역할로 받아 주세요.',
    ok: '이 번호로 전화하기',
  });
  if (phone) await act({ type: 'startCalls', phone });
}
