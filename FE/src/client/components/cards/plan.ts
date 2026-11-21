import { html, nothing, type TemplateResult } from 'lit-html';
import type { Card, Listing, Visit } from '../../../shared/types.js';
import { CHECK_LABEL, CONTACT_LABEL, PRICE_LABEL, VISIT_LABEL } from '../../../shared/labels.js';
import { dateOnly, dateTime, depRent, hm } from '../../../shared/format.js';
import { act, openPanel, state, toast } from '../../store.js';
import { copyText } from '../common.js';
import { brokerOf, dongName, listingCard, typeName } from './listing.js';
import { miniMap } from './minimap.js';

const BRING = [
  '등기부 원본(소유자·근저당 다시 확인)',
  '수압, 곰팡이, 채광, 소음',
  '전입신고와 확정일자 받을 수 있는지',
];

function planText(visits: { v: Visit; l: Listing }[]): string {
  const lines = visits.map(({ v, l }) => {
    const b = brokerOf(l);
    return `${hm(v.at)} ${b?.name ?? ''} · ${l.building} ${l.unit} ${depRent(l.deposit, l.rent)} · ${CONTACT_LABEL[l.contact].text}`;
  });
  return [
    `살구 방문 계획 ${visits[0] ? dateOnly(visits[0].v.at) : ''}`,
    ...lines,
    '',
    '챙길 것',
    ...BRING.map((b) => `- ${b}`),
  ].join('\n');
}

/** S-07 미팅 계획서와 확정 통화 */
export function planCard(_card: Extract<Card, { kind: 'plan' }>): TemplateResult {
  const chat = state.chat;
  const plan = chat?.plan;
  if (!chat || !plan) return html`<article class="card folded">방문 계획이 없어요.</article>`;
  const visits = plan.visitIds
    .map((id) => chat.visits.find((v) => v.id === id))
    .filter((v): v is Visit => Boolean(v))
    .map((v) => ({ v, l: chat.listings.find((l) => l.id === v.listingId)! }))
    .filter((x) => x.l)
    .sort((a, b) => a.v.order - b.v.order);
  const talk = state.session?.kakaoTalk;
  return html`<article class="card plan" data-testid="plan-card">
    <div class="card-head">
      <h3>${dateOnly(plan.start)} ${hm(plan.start)}~${hm(plan.end)} · ${visits.length}곳</h3>
    </div>
    <div class="notify ${talk ? 'on' : ''}">
      ${
        talk
          ? html`<p>카카오톡 '나에게 보내기'로 방문 전날 저녁과 1시간 전에 알려 드려요.</p>`
          : html`<p>지금은 이 화면이 열려 있을 때 화면 알림으로 알려 드려요.</p>
              <button class="link" @click=${() => openPanel('sched')}>카카오톡 알림 연결</button>`
      }
    </div>
    ${miniMap(
      visits.map(({ v, l }) => ({
        lat: l.lat,
        lng: l.lng,
        label: hm(v.at),
        kind: 'visit' as const,
        tone: VISIT_LABEL[v.status].tone,
        sub: String(v.order),
      })),
      { mode: 'route', route: true, caption: '방문 동선' },
    )}
    <ol class="timeline">
      ${visits.map(
        ({ v, l }) =>
          html`<li class="tl-item" data-testid="visit-item" data-status=${v.status}>
            <div class="tl-time">
              <strong>${hm(v.at)}</strong>
            </div>
            ${listingCard(
              l,
              html`<p class="note">
                  ${brokerOf(l)?.name ?? ''} · 실거래 대비 ${PRICE_LABEL[l.priceVerdict].text}
                </p>
                ${v.brokerSaid ? html`<p class="said">중개사: "${v.brokerSaid}"</p>` : nothing}
                ${
                  v.status === 'proposed' && v.proposedAt
                    ? html`<div class="actions">
                        <button
                          class="btn-line small"
                          ?disabled=${state.pending}
                          @click=${() => act({ type: 'acceptProposal', visitId: v.id })}
                        >
                          ${hm(v.proposedAt)}로 확정하기
                        </button>
                      </div>`
                    : nothing
                }`,
              { compact: true },
            )}
            ${v.travelNext ? html`<p class="travel">다음 장소까지 ${v.travelNext.mode} ${v.travelNext.minutes}분</p>` : nothing}
          </li>`,
      )}
    </ol>
    <details>
      <summary>방문 때 챙길 것</summary>
      <ul class="reasons">
        ${BRING.map((b) => html`<li>${b}</li>`)}
      </ul>
    </details>
    <div class="actions">
      <button
        class="btn-primary"
        @click=${async () => toast((await copyText(planText(visits))) ? '계획서를 복사했어요.' : '복사하지 못했어요.')}
      >
        계획서 복사
      </button>
      <button class="btn-ghost" @click=${() => openPanel('sched')}>일정 탭에서 보기</button>
    </div>
  </article>`;
}

/** S-08 최종 추천: 방문 후보 비교표 */
export function finalCard(card: Extract<Card, { kind: 'final' }>): TemplateResult {
  const chat = state.chat;
  if (!chat) return html``;
  const rows = card.ranking
    .map((r) => ({ ...r, l: chat.listings.find((l) => l.id === r.listingId)! }))
    .filter((r) => r.l);
  const top = rows[0];
  if (!top) return html`<article class="card folded">비교할 매물이 없어요.</article>`;
  const dong = (id: string) => chat.search?.dongs.find((d) => d.id === id);
  const visitOf = (l: Listing) => chat.visits.find((v) => v.listingId === l.id && v.status !== 'cancelled');
  return html`<article class="card final" data-testid="final-card">
    <section class="winner">
      <p class="note">1위</p>
      ${listingCard(
        top.l,
        html`<p>실제 부담(환산월세 + 관리비) <span class="money">월 ${top.burden}만 원</span></p>`,
      )}
    </section>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>순위</th>
            <th>매물</th>
            <th>보증금/월세</th>
            <th>실거래 대비</th>
            <th>관리비</th>
            <th>실제 부담</th>
            <th>통근·환승</th>
            <th>버스</th>
            <th>준공</th>
            <th>입주</th>
            <th>등기·대출</th>
            <th>방문</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map((r, i) => {
            const d = dong(r.l.dongId);
            const v = visitOf(r.l);
            return html`<tr>
              <td>${i + 1}</td>
              <td>
                ${r.l.no}. ${r.l.building}
                <span class="muted">${dongName(r.l.dongId)} ${typeName(r.l.type)}</span>
              </td>
              <td>${depRent(r.l.deposit, r.l.rent)}</td>
              <td>${PRICE_LABEL[r.l.priceVerdict].text}</td>
              <td>${r.l.fee}만</td>
              <td class="money">${r.burden}만</td>
              <td>${d ? `${d.commute.minutes}분 · ${d.commute.transfers}회` : '-'}</td>
              <td>${d ? `${d.bus.interval}분 · ${d.bus.last}` : '-'}</td>
              <td>${r.l.built}</td>
              <td>${r.l.moveIn}</td>
              <td>${CHECK_LABEL[r.l.check].text}</td>
              <td>${v ? `${CONTACT_LABEL[r.l.contact].text} ${dateTime(v.at)}` : '-'}</td>
            </tr>`;
          })}
        </tbody>
      </table>
    </div>
    <p class="note">
      숫자 비교일 뿐 계약 판단이 아니에요. 계약은 방을 직접 보고 공인중개사와 함께 정해 주세요.
    </p>
  </article>`;
}
