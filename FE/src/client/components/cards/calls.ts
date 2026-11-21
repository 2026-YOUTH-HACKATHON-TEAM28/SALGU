import { html, nothing, type TemplateResult } from 'lit-html';
import type { Call, CallPrep, Card } from '../../../shared/types.js';
import { REGISTRY_REPLY_LABEL, callLabel, isCallActive } from '../../../shared/labels.js';
import { depRent, hm, dateTime } from '../../../shared/format.js';
import { act, state, toast, update } from '../../store.js';
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
  return html`<article class="card prep" data-testid="callprep-card">
    <section>
      <h3>전화할 곳</h3>
      <ul class="plain">
        ${dongs.map(
          (d) =>
            html`<li>
              <strong>${d.name}</strong>
              <span class="muted">${d.brokers.map((b) => `${b.name}(${b.regNo})`).join(', ')}</span>
            </li>`,
        )}
      </ul>
      <p class="note">
        매물이 있으면 그 호실 등기부를 살구 수신 번호(문자·팩스)로 보내 달라고 부탁해요. 받은 등기부로 위험을
        먼저 확인해 드려요.
      </p>
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
          ${
            share.condition
              ? `근처에 월세 ${rent ?? '○○'}만 원 이하 방이 있을까요?`
              : '근처에 원룸이 있을까요?'
          }
          ${prep.moveIn ? ` 입주는 ${prep.moveIn}이에요.` : ''}${prep.term ? ` 계약은 ${prep.term} 생각해요.` : ''}
        </li>
        <li>매물이 있으면 그 호실 등기부를 살구 번호로 미리 보내 주실 수 있을까요?</li>
        ${share.slot && prep.visitSlot ? html`<li>보여 주실 수 있는 시간이 언제일까요?</li>` : nothing}
      </ol>
    </details>
    ${
      inBusinessHours()
        ? nothing
        : html`<p class="hours">
            지금은 영업시간(월~토 9~19시)이 아니에요. 실서비스에서는 다음 영업 시작에 걸도록 예약해요. 지금은
            시험 서버라 바로 진행해요.
          </p>`
    }
    <div class="actions">
      <button
        class="btn-primary"
        ?disabled=${!ready || state.pending}
        @click=${() => act({ type: 'startCalls' })}
        data-testid="start-calls"
      >
        이대로 전화하기
      </button>
      ${ready ? nothing : html`<span class="note">입주 희망일과 계약 기간을 골라 주세요.</span>`}
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
                .map((l) => `${l.building} ${typeName(l.type)} ${l.area}㎡ ${depRent(l.deposit, l.rent)}`)
                .join(', ')
            : nothing
        }
      </span>
    </button>
    ${
      open
        ? html`<div class="call-detail">
            <p class="muted">
              전화 ${broker?.phone ?? ''} · 등록번호
              ${broker?.regNo ?? ''}${c.attempts > 1 ? ` · ${c.attempts}번째 통화` : ''}
            </p>
            ${c.slots.length ? html`<p>보여 줄 수 있는 시간: ${c.slots.map(dateTime).join(', ')}</p>` : nothing}
            ${c.registryReply ? html`<p>등기부: ${REGISTRY_REPLY_LABEL[c.registryReply]}</p>` : nothing}
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
                      @click=${async () => toast((await copyText(c.smsDraft ?? '')) ? '문자 초안을 복사했어요.' : '복사하지 못했어요.')}
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
  const regs = calls.filter((c) => c.registryReply === 'will_send').length;
  const noAnswer = calls.filter((c) => c.outcome === 'no_answer' || c.status === 'retry_wait').length;
  const dongIds = [...new Set(calls.map((c) => c.dongId))];
  return html`<article class="card calls" data-testid="calls-card">
    <div class="call-summary">
      <p>
        통화 <strong>${done}/${calls.length}</strong> · 방 있음 ${found} · 등기 받음 ${regs} · 안 받음
        ${noAnswer}
      </p>
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
    <p class="note">통화 첫마디에 AI 비서임을 밝혀요. 같은 사무소는 하루 1번, 하루 최대 10통이에요.</p>
  </article>`;
}
