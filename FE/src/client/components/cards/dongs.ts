import { html, nothing, type TemplateResult } from 'lit-html';
import type { Card, CondKey, DongResult } from '../../../shared/types.js';
import { COND_META } from '../../../shared/labels.js';
import { depRent } from '../../../shared/format.js';
import { act, openPanel, send, state } from '../../store.js';
import { miniMap, type MiniPoint } from './minimap.js';
import { condText } from '../prefs.js';

function latestDongsCardId(): string | null {
  const msgs = state.chat?.messages ?? [];
  for (let i = msgs.length - 1; i >= 0; i--) {
    const c = msgs[i]?.cards.find((x) => x.kind === 'dongs');
    if (c) return c.id;
  }
  return null;
}

function commuteText(d: DongResult): string {
  return d.commute.route.join(' · ');
}

/** S-03 살만한 동네 */
export function dongsCard(card: Extract<Card, { kind: 'dongs' }>): TemplateResult {
  const { dongs, asOf } = card.result;
  const latest = latestDongsCardId() === card.id;
  const selected = new Set(state.chat?.selectedDongIds ?? []);
  const wp = state.meta?.workplaces.find((w) => w.id === card.workplace);
  const points: MiniPoint[] = [
    ...dongs.map((d) => ({
      lat: d.lat,
      lng: d.lng,
      label: d.name,
      kind: 'dong' as const,
      sub: String(d.rank),
    })),
    ...(wp ? [{ lat: wp.lat, lng: wp.lng, label: wp.name, kind: 'company' as const }] : []),
  ];
  const calling = Boolean(state.chat?.batch && !state.chat.batch.doneAt);
  return html`<article class="card dongs" data-testid="dongs-card">
    ${miniMap(points, { mode: 'dong', caption: '살만한 동네 지도' })}
    <p class="note">과거 실거래(최근 12개월, ${asOf} 기준) · 환산월세는 만 원</p>
    <ol class="dong-list">
      ${dongs.map(
        (d) =>
          html`<li class="dong-row" data-testid="dong-row">
            ${
              latest
                ? html`<input
                    type="checkbox"
                    class="dong-check"
                    aria-label="${d.name} 고르기"
                    .checked=${selected.has(d.id)}
                    ?disabled=${state.pending || calling}
                    @change=${() => act({ type: 'toggleDong', dongId: d.id })}
                  />`
                : nothing
            }
            <button class="dong-main" @click=${() => openPanel('map', { mode: 'dong', focus: d.id })}>
              <div class="dong-head">
                <span class="rank">${d.rank}</span>
                <strong>${d.name}</strong>
                <span class="muted">${d.gu} · ${d.station}역</span>
                <span class="score">점수 ${d.score}</span>
              </div>
              <dl class="facts">
                <div>
                  <dt>실거래</dt>
                  <dd>
                    조건 비슷한 계약 ${d.dealCount}건 · 환산월세 ${d.rentRange[0]}~${d.rentRange[1]} · 중간값
                    <span class="money">${d.median}</span>
                  </dd>
                </div>
                <div>
                  <dt>출퇴근</dt>
                  <dd>
                    ${wp?.name ?? '회사'}까지 <span class="money">${d.commute.minutes}분</span> · 환승
                    ${d.commute.transfers}회 · ${commuteText(d)}
                  </dd>
                </div>
                <div>
                  <dt>버스</dt>
                  <dd>${d.bus.route}번 배차 ${d.bus.interval}분 · 막차 ${d.bus.last}</dd>
                </div>
                <div>
                  <dt>전화</dt>
                  <dd>등록 중개사무소 ${d.brokers.length}곳</dd>
                </div>
              </dl>
            </button>
          </li>`,
      )}
    </ol>
    ${
      latest
        ? html`<div class="actions">
            <button
              class="btn-primary"
              ?disabled=${selected.size === 0 || state.pending || calling}
              @click=${() => act({ type: 'prepCalls', dongIds: [...selected] })}
              data-testid="dongs-call"
            >
              고른 동네 중개사무소들에 전화
            </button>
          </div>`
        : nothing
    }
  </article>`;
}

/** "n번 자세히 알려줘": 동네 한 장 설명 */
export function dongDetailCard(card: Extract<Card, { kind: 'dongDetail' }>): TemplateResult {
  const d = card.dong;
  return html`<article class="card" data-testid="dong-detail">
    <div class="card-head">
      <h3>${d.rank}. ${d.name} <span class="muted">${d.gu}</span></h3>
      <span class="score">점수 ${d.score}</span>
    </div>
    <dl class="facts">
      <div>
        <dt>출퇴근</dt>
        <dd>${d.commute.minutes}분 · 환승 ${d.commute.transfers}회 · ${commuteText(d)}</dd>
      </div>
      <div>
        <dt>버스</dt>
        <dd>${d.bus.route}번 배차 ${d.bus.interval}분 · 막차 ${d.bus.last}</dd>
      </div>
      <div>
        <dt>계약 있던 건물</dt>
        <dd>${d.buildings.join(', ')}</dd>
      </div>
    </dl>
    <h4>최근 계약 예시</h4>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>건물</th>
            <th>유형</th>
            <th>면적</th>
            <th>준공</th>
            <th>보증금/월세</th>
            <th>계약</th>
          </tr>
        </thead>
        <tbody>
          ${card.deals.map(
            (x) =>
              html`<tr>
                <td>${x.building}</td>
                <td>${x.type === 'officetel' ? '오피스텔' : '원룸·빌라'}</td>
                <td>${x.area}㎡</td>
                <td>${x.built}</td>
                <td>${depRent(x.deposit, x.rent)}</td>
                <td>${x.month}</td>
              </tr>`,
          )}
        </tbody>
      </table>
    </div>
    <h4>전화할 중개사무소</h4>
    <ul class="plain">
      ${d.brokers.map((b) => html`<li>${b.name} <span class="muted">등록번호 ${b.regNo}</span></li>`)}
    </ul>
  </article>`;
}

function lossLabel(key: CondKey, suggest: number | string | null): string {
  const label = COND_META.find((m) => m.key === key)?.label ?? key;
  if (suggest === null || suggest === 'any') return `${label} 상관없게`;
  return `${label} ${condText(key, suggest)}까지`;
}

/** 맞는 동네 0곳: 가장 많이 걸러 낸 조건부터 넓히기 제안 */
export function noMatchCard(card: Extract<Card, { kind: 'noMatch' }>): TemplateResult {
  return html`<article class="card" data-testid="nomatch-card">
    ${
      card.losses.length
        ? html`<ul class="plain loss">
            ${card.losses.map(
              (l) =>
                html`<li>
                  <button
                    class="btn-line"
                    ?disabled=${state.pending}
                    @click=${() => act({ type: 'widen', key: l.key, value: l.suggest === 'any' ? 'any' : l.suggest })}
                    data-testid=${`widen-${l.key}`}
                  >
                    ${lossLabel(l.key, l.suggest)} 넓혀줘
                  </button>
                  <span class="note">이 조건 때문에 ${l.count}건이 빠졌어요</span>
                </li>`,
            )}
          </ul>`
        : html`<p>회사 위치를 다시 확인해 주세요.</p>`
    }
    <div class="actions">
      <button class="btn-ghost" @click=${() => send('조건 바꿀래')}>조건 직접 바꾸기</button>
    </div>
  </article>`;
}
