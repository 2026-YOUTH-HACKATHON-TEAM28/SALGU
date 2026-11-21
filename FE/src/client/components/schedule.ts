import { html, nothing, type TemplateResult } from 'lit-html';
import type { ScheduleItem } from '../../shared/types.js';
import { PRICE_LABEL } from '../../shared/labels.js';
import { dateOnly, depRent, hm } from '../../shared/format.js';
import { actOn, openPanel, setKakaoTalk, state, testNotify } from '../store.js';
import { confirmAction } from './common.js';
import { typeName } from './cards/listing.js';

const ASK = [
  '관리비에 포함된 항목(인터넷, 수도, 청소)',
  '전입신고와 확정일자가 가능한지',
  '보증금 반환 시기와 방법',
  '수리는 누가 하는지(도배, 장판, 보일러)',
];

function kakaoBox(): TemplateResult {
  const s = state.session;
  const guest = s?.user?.kind === 'guest';
  return html`<section class="kakao-box" data-testid="kakao-box">
    <div class="kakao-row">
      <strong>카카오톡 알림</strong>
      <span class="badge ${s?.kakaoTalk ? 'tone-ok' : 'tone-muted'}"
        ><span class="dot"></span>${s?.kakaoTalk ? '연결됨(시험 연결)' : '미연결 · 화면 알림'}</span
      >
    </div>
    <p class="note">
      ${
        s?.kakaoTalk
          ? '방문 전날 저녁과 1시간 전에 본인 카카오톡으로 알려 드려요. 지금은 시험 연결이라 실제로 보내지 않아요.'
          : guest
            ? '카카오로 로그인하면 카카오톡으로 알림을 받을 수 있어요. 지금은 이 화면이 열려 있을 때 화면 알림으로 알려 드려요.'
            : '연결하면 카카오 화면에서 카카오톡 메시지 전송에 동의를 받아요. 지금은 화면 알림으로 알려 드려요.'
      }
    </p>
    <div class="actions">
      ${
        s?.kakaoTalk
          ? html`<button class="btn-ghost small" @click=${testNotify}>시험 알림</button>
              <button class="btn-ghost small" @click=${() => setKakaoTalk(false)}>연결 해제</button>`
          : html`<button
              class="btn-kakao small"
              ?disabled=${guest}
              @click=${() => setKakaoTalk(true)}
              data-testid="kakao-connect"
            >
              카카오톡 연결
            </button>`
      }
    </div>
  </section>`;
}

function visitItem(it: ScheduleItem): TemplateResult {
  const { visit: v, listing: l, broker: b } = it;
  return html`<li class="sched-item" data-testid="sched-item">
    <div class="sched-time">
      <strong>${hm(v.at)}</strong>
      <span class="badge tone-ok"><span class="dot"></span>방문 확정</span>
    </div>
    <div class="sched-body">
      <p>
        <strong>${b?.name ?? '중개사무소'}</strong>
        <span class="muted">실거래 대비 ${PRICE_LABEL[l.priceVerdict].text}</span>
      </p>
      <p>
        ${l.building} ${l.unit} · ${typeName(l.type)} ${l.area}㎡ ·
        <span class="money">${depRent(l.deposit, l.rent)}</span>
      </p>
      <p class="note">통화로 확정 · 중개사: "${v.brokerSaid ?? ''}"</p>
      <p class="note">등록번호 ${b?.regNo ?? ''} · ${b?.phone ?? ''} · ${it.dongName} ${it.station}역</p>
      ${v.changeRequested ? html`<p class="note warn-text">일정 변경을 요청했어요. 중개사 답을 기다리는 중이에요(시뮬레이션).</p>` : nothing}
      <div class="actions">
        <button class="btn-ghost small" @click=${() => openPanel('map', { mode: 'route', focus: l.id })}>
          위치
        </button>
        <button
          class="btn-ghost small"
          ?disabled=${v.changeRequested}
          @click=${() => actOn(it.chatId, { type: 'requestChange', visitId: v.id })}
        >
          일정 변경 전화 요청
        </button>
        <button
          class="btn-ghost small"
          @click=${() => {
            if (confirmAction(`${dateOnly(v.at)} ${hm(v.at)} ${l.building} 방문을 취소할까요?`)) {
              void actOn(it.chatId, { type: 'cancelVisit', visitId: v.id });
            }
          }}
        >
          취소
        </button>
      </div>
    </div>
  </li>`;
}

/** S-09 일정 탭 */
export function scheduleView(): TemplateResult {
  const items = state.schedule;
  const days = new Map<string, ScheduleItem[]>();
  for (const it of items) {
    const key = it.visit.at.slice(0, 10);
    days.set(key, [...(days.get(key) ?? []), it]);
  }
  return html`<div class="schedule" data-testid="schedule">
    ${kakaoBox()}
    ${
      items.length
        ? [...days.entries()].map(
            ([, list]) =>
              html`<section class="sched-day">
                <h3>${dateOnly(list[0]!.visit.at)}</h3>
                <ul class="plain">
                  ${list.map(visitItem)}
                </ul>
              </section>`,
          )
        : html`<p class="empty">
            아직 확정된 방문이 없어요. 매물 확인 뒤 [추천 매물로 미팅 잡기]를 누르면 중개사무소에 확정 전화를
            걸고, 확정된 방문만 여기에 보여요.
          </p>`
    }
    <details class="ask-list">
      <summary>방문 때 물어볼 것</summary>
      <ul class="reasons">
        ${ASK.map((a) => html`<li>${a}</li>`)}
      </ul>
    </details>
    <p class="note">일정 변경과 취소 전화는 아직 시뮬레이션이에요.</p>
  </div>`;
}
