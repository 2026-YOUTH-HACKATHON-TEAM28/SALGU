import { html, nothing, type TemplateResult } from 'lit-html';
import type { Card, Listing } from '../../../shared/types.js';
import { CHECK_LABEL, REGISTRY_REPLY_LABEL, RISK_LABEL } from '../../../shared/labels.js';
import { dateTime, won } from '../../../shared/format.js';
import { act, state, update } from '../../store.js';
import { badge } from '../common.js';
import { brokerOf, listingCard } from './listing.js';
import { miniMap } from './minimap.js';

function checkBody(l: Listing): TemplateResult {
  const b = brokerOf(l);
  const open = state.ui.openChecks.has(l.id);
  const d = l.detail;
  const toggle = () =>
    update((s) => {
      if (open) s.ui.openChecks.delete(l.id);
      else s.ui.openChecks.add(l.id);
    });
  return html`<dl class="facts small-facts">
      <div>
        <dt>중개사무소</dt>
        <dd>${b?.name ?? ''} <span class="muted">등록번호 ${b?.regNo ?? ''}</span></dd>
      </div>
      <div>
        <dt>입주</dt>
        <dd>${l.moveIn}</dd>
      </div>
      <div>
        <dt>보여 줄 시간</dt>
        <dd>${l.slots.map(dateTime).join(', ') || '통화로 확인 못 함'}</dd>
      </div>
    </dl>
    ${
      d
        ? html`<ol class="steps">
              <li><span class="step-k">① 등기 → 소재지</span><span>${d.address}</span></li>
              <li>
                <span class="step-k">② 건축물대장</span>
                <span
                  >${d.buildingUse} · 사용승인
                  ${d.approvedYear}년${d.violation ? html` · <strong class="bad">위반건축물</strong>` : ''}</span
                >
              </li>
              <li>
                <span class="step-k">③ 전세대출·보증</span>
                <span>${d.loanOk ? '가능' : html`<strong class="bad">불가 사유 있음</strong>`}</span>
              </li>
              <li>
                <span class="step-k">④ 등기 위험</span>
                <span class="step-v"
                  >${badge(RISK_LABEL[d.risk])}
                  ${d.ratio !== null ? html`<span>(근저당 + 보증금) ÷ 매매 시세 <span class="money">${d.ratio}%</span></span>` : html`<span>시세 모름</span>`}</span
                >
              </li>
            </ol>
            <button class="link" aria-expanded=${open} @click=${toggle}>
              ${open ? '이유 접기' : '판정 이유 보기'}
            </button>
            ${
              open
                ? html`<ul class="reasons">
                    <li>현재 소유자 ${d.owner}${d.owners > 1 ? ` 외 ${d.owners - 1}명` : ''}</li>
                    <li>
                      근저당
                      ${d.mortgage ? won(d.mortgage) : '없음'}${d.seizure ? ' · 압류·경매 기록' : ''}${d.trust ? ' · 신탁' : ''}${
                        d.leaseRight ? ' · 전세권·임차권' : ''
                      }
                    </li>
                    ${d.salePrice ? html`<li>매매 시세(예시) ${won(d.salePrice)}</li>` : nothing}
                    ${d.loanReasons.map((r) => html`<li>${r}</li>`)}
                    ${d.riskReasons.map((r) => html`<li>${r}</li>`)}
                    <li class="muted">판정 규칙 ${d.ruleVersion}. 주민등록번호는 읽자마자 가렸어요.</li>
                  </ul>`
                : nothing
            }`
        : html`<p class="note">
            등기부: ${l.registryReply ? REGISTRY_REPLY_LABEL[l.registryReply] : '받지 못함'}.
            ${l.registryReply === 'at_visit' ? '방문 때 원본으로 소유자와 근저당을 꼭 확인해 주세요.' : '등기부 없이는 위험을 판정하지 않아요.'}
          </p>`
    }`;
}

/** S-06 매물 확인 */
export function checksCard(_card: Extract<Card, { kind: 'checks' }>): TemplateResult {
  const chat = state.chat;
  const ids = new Set(chat?.batch?.calls.map((c) => c.id));
  const listings = (chat?.listings ?? []).filter((l) => ids.has(l.callId));
  if (!listings.length) return html`<article class="card folded">확인할 매물이 없어요.</article>`;
  const order: Listing['check'][] = ['recommend', 'caution', 'registry_wait', 'unchecked', 'exclude'];
  const sorted = [...listings].sort((a, b) => order.indexOf(a.check) - order.indexOf(b.check) || a.no - b.no);
  const wp = state.meta?.workplaces.find((w) => w.id === chat?.conditions.workplace?.value);
  const planning = chat?.visits.some((v) => v.status === 'requesting');
  return html`<article class="card checks" data-testid="checks-card">
    ${miniMap(
      [
        ...sorted.map((l) => ({
          lat: l.lat,
          lng: l.lng,
          label: '',
          kind: 'listing' as const,
          tone: CHECK_LABEL[l.check].tone,
          sub: String(l.no),
        })),
        ...(wp ? [{ lat: wp.lat, lng: wp.lng, label: wp.name, kind: 'company' as const }] : []),
      ],
      { mode: 'listing', caption: '찾은 매물 지도' },
    )}
    <div class="legend">
      ${(['recommend', 'caution', 'exclude', 'registry_wait'] as const).map((k) => badge(CHECK_LABEL[k]))}
    </div>
    <div class="listing-list">${sorted.map((l) => listingCard(l, checkBody(l)))}</div>
    <div class="actions">
      <button
        class="btn-primary"
        ?disabled=${state.pending || planning}
        @click=${() => act({ type: 'planVisits', includeCaution: false })}
        data-testid="plan-recommend"
      >
        추천 매물로 미팅 잡기
      </button>
      <button
        class="btn-ghost"
        ?disabled=${state.pending || planning}
        @click=${() => act({ type: 'planVisits', includeCaution: true })}
        data-testid="plan-caution"
      >
        주의 매물까지 미팅 잡기
      </button>
    </div>
    <p class="note">
      숫자 비교와 서류 확인일 뿐 계약 판단은 아니에요. 계약은 방을 직접 보고 공인중개사와 함께 정해 주세요.
    </p>
  </article>`;
}
