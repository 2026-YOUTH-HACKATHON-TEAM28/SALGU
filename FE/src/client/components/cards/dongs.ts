import { html, nothing, type TemplateResult } from 'lit-html';
import type { Card, CondKey, DongResult } from '../../../shared/types.js';
import { COND_META } from '../../../shared/labels.js';
import { busLabel, commuteLabel, depRent } from '../../../shared/format.js';
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
  return d.commute?.route.join(', ') ?? '';
}

/** S-03 살만한 동네 */
export function dongsCard(card: Extract<Card, { kind: 'dongs' }>): TemplateResult {
  const { dongs, asOf } = card.result;
  const latest = latestDongsCardId() === card.id;
  const selected = new Set(state.chat?.selectedDongIds ?? []);
  const point = state.chat?.workplacePoint;
  const known = state.meta?.workplaces.find((w) => w.id === card.workplace);
  const wp = point?.value === card.workplace ? point : (known ?? null);
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
  const wpName = wp?.name ?? (card.workplace || '회사');
  return html`<article class="card dongs" data-testid="dongs-card">
    ${miniMap(points, { mode: 'dong', caption: `살만한 동네 ${dongs.length}곳 · ${wpName} 출근 기준` })}
    <ol class="dong-list">
      ${dongs.map(
        (d) =>
          html`<li class="dong-row ${d.rank === 1 ? 'first' : ''}" data-testid="dong-row">
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
                <span class="muted">${d.gu}${d.station ? ` · ${d.station}역` : ''}</span>
                <span class="score">점수 ${d.score}</span>
              </div>
              <p class="deal-line">
                과거 실거래 <b>${d.dealCount}건</b> · 환산월세 <b>${d.rentRange[0]}~${d.rentRange[1]}만</b>
                <span class="muted">같은 조건 중간 ${d.median}만 · 최근 12개월 계약</span>
              </p>
              <div class="commute-box">
                <strong
                  >${d.commute ? `${wpName}까지 ${commuteLabel(d)}` : `${wpName}까지 통근 시간은 계산 전`}</strong
                >
                <span>${commuteText(d)}</span>
              </div>
              <ul class="ticks">
                ${d.bus ? html`<li>버스 ${busLabel(d)}</li>` : nothing}
                <li>
                  ${d.brokers.length ? `전화할 등록 중개사무소 ${d.brokers.length}곳` : '중개사무소는 고르면 실거래 DB에서 불러와요'}
                </li>
              </ul>
            </button>
          </li>`,
      )}
    </ol>
    ${
      latest
        ? html`<div class="card-foot">
            <button
              class="btn-primary"
              ?disabled=${selected.size === 0 || state.pending || calling}
              @click=${() => act({ type: 'prepCalls', dongIds: [...selected] })}
              data-testid="dongs-call"
            >
              고른 동네 중개사무소들에 전화
            </button>
            <span class="note">동네마다 중개사무소 최대 3곳 · 비슷한 방과 보여 줄 시간 묻기</span>
          </div>`
        : nothing
    }
    ${
      dongs.some((d) => d.source === 'agent')
        ? html`<p class="foot-note">
            과거 실거래 기준: 살구 추천 엔진(최근 12개월 전월세 실거래). 통근 시간은 교통 데이터 연결 뒤에
            보여 드려요. 지금 나온 방은 전화로 확인해요.
          </p>`
        : html`<p class="foot-note">
            과거 실거래 기준: 서울시 부동산 전월세가 정보(최근 12개월 계약) · 카카오맵 대중교통 · 서울시
            버스운행노선 · 기준일 ${asOf}. 지금 나온 방은 전화로 확인해요. 시험용 예시 데이터예요.
          </p>`
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
        <dd>${commuteLabel(d)}${d.commute ? ` · ${commuteText(d)}` : ''}</dd>
      </div>
      <div>
        <dt>버스</dt>
        <dd>${busLabel(d)}</dd>
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
