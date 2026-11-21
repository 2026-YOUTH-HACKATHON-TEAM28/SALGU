import { html, nothing, type TemplateResult } from 'lit-html';
import type { Broker, Listing } from '../../../shared/types.js';
import { CONTACT_LABEL, PRICE_LABEL } from '../../../shared/labels.js';
import { depRent } from '../../../shared/format.js';
import { state } from '../../store.js';
import { badge } from '../common.js';

export function brokerOf(l: Listing): Broker | undefined {
  return state.chat?.brokers.find((b) => b.id === l.brokerId);
}

export function dongName(id: string): string {
  return state.meta?.dongs.find((d) => d.id === id)?.name ?? '';
}

/** 통화에서 확인하지 못한 값인지 */
export function miss(l: Listing, key: string): boolean {
  return Boolean(l.unverified?.includes(key));
}

export function typeName(t: Listing['type']): string {
  return t === 'officetel' ? '오피스텔' : '원룸·빌라';
}

/** 매물 카드. 어느 화면에서든 연락 상태는 머리 오른쪽, 실거래 대비는 가격 줄 바로 아래에 같은 문구로 */
export function listingCard(
  l: Listing,
  body: TemplateResult | typeof nothing = nothing,
  opts: { compact?: boolean; lead?: TemplateResult } = {},
) {
  const contact = CONTACT_LABEL[l.contact];
  return html`<div
    class="listing ${opts.compact ? 'compact' : ''}"
    data-testid="listing"
    data-listing=${l.id}
  >
    <div class="listing-head">
      ${opts.lead ?? nothing}
      <span class="lno">${l.no}</span>
      <div class="listing-title">
        <strong>${l.building}</strong>
        <span class="muted"
          >${dongName(l.dongId)} · ${typeName(l.type)}
          ${miss(l, 'area') ? '면적 확인 필요' : `${l.area}㎡`}${
            miss(l, 'floor') ? '' : ` · ${l.floor}층`
          }</span
        >
      </div>
      ${badge(contact, { live: l.contact === 'contacting', testid: 'contact-status' })}
    </div>
    <p class="listing-price">
      <span class="money">${miss(l, 'price') ? '가격 확인 필요' : depRent(l.deposit, l.rent)}</span>
      <span class="muted">보증금/월세(만 원) · 관리비 ${miss(l, 'fee') ? '확인 필요' : `${l.fee}만`}</span>
    </p>
    <div class="listing-check">
      ${badge(PRICE_LABEL[l.priceVerdict], { testid: 'price-status' })}
      <span class="note">같은 조건 과거 실거래 대비</span>
    </div>
    ${body}
  </div>`;
}
