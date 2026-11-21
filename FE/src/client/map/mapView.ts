import { html, nothing, type TemplateResult } from 'lit-html';
import type { Listing } from '../../shared/types.js';
import { CONTACT_LABEL, PRICE_LABEL } from '../../shared/labels.js';
import { busLabel, commuteLabel, depRent, hm } from '../../shared/format.js';
import { state, ui, type MapMode } from '../store.js';
import { listingCard } from '../components/cards/listing.js';
import { createProvider, esc, SEOUL, type LatLng, type MapProvider } from './provider.js';
import { COMPANY_ICON } from './pins.js';

const MODES: { id: MapMode; label: string }[] = [
  { id: 'dong', label: '동네' },
  { id: 'listing', label: '매물' },
  { id: 'route', label: '동선' },
];

let provider: MapProvider | null = null;
let providerEl: HTMLElement | null = null;
let creating: Promise<void> | null = null;
let lastSig = '';

function visibleListings(): Listing[] {
  return state.chat?.listings ?? [];
}

function routeItems() {
  const chat = state.chat;
  if (!chat?.plan) return [];
  return chat.plan.visitIds
    .map((id) => chat.visits.find((v) => v.id === id))
    .filter((v) => v && v.status !== 'cancelled' && v.status !== 'failed')
    .map((v) => ({ v: v!, l: chat.listings.find((l) => l.id === v!.listingId)! }))
    .filter((x) => x.l)
    .sort((a, b) => a.v.at.localeCompare(b.v.at));
}

function workplace() {
  const id = state.chat?.conditions.workplace?.value;
  const point = state.chat?.workplacePoint;
  if (point && point.value === id) return point;
  return state.meta?.workplaces.find((w) => w.id === id) ?? null;
}

const companyPin = (name: string) => `<span class="lpin k-company">${COMPANY_ICON}${esc(name)}</span>`;

/** 지금 상태를 지도에 그려요(바뀐 게 있을 때만) */
function paint(p: MapProvider): void {
  const chat = state.chat;
  const { mapMode: mode, mapFocus: focus, mapLayers } = state.ui;
  const sig = JSON.stringify([chat?.id, chat?.rev, mode, focus, mapLayers, p.kind]);
  if (sig === lastSig) return;
  lastSig = sig;
  p.clear();
  const pts: LatLng[] = [];
  const wp = workplace();

  if (mapLayers.stations) {
    for (const s of state.meta?.stations ?? []) {
      p.marker({
        lat: s.lat,
        lng: s.lng,
        html: '<span class="pin station"></span>',
        title: `${s.name}역`,
        popup: [`${s.name}역`, `${s.lines}호선`],
      });
    }
  }
  if (wp) {
    p.marker({
      lat: wp.lat,
      lng: wp.lng,
      html: companyPin(wp.name),
      title: `회사 ${wp.name}`,
      popup: ['회사(학교)', wp.name],
    });
    if (mapLayers.commuteRange)
      p.circle({ lat: wp.lat, lng: wp.lng, radius: 6000, color: '#2f6fb3', dashed: true });
  }

  if (mode === 'dong') {
    for (const d of chat?.search?.dongs ?? []) {
      p.circle({ lat: d.lat, lng: d.lng, radius: 650, color: '#f08a4b' });
      p.marker({
        lat: d.lat,
        lng: d.lng,
        html: `<span class="lpin ${d.rank === 1 ? 'k-first' : 'k-dong'}"><b>${d.rank}</b>${esc(d.name)}</span>`,
        title: `${d.rank}순위 ${d.name}`,
        popup: [`${d.rank}. ${d.name}`, `출퇴근 ${commuteLabel(d)}`, `환산월세 중간값 ${d.median}만 원`],
        onClick: () => ui({ mapFocus: d.id, sheetOpen: true }),
      });
      for (const b of d.brokers) {
        p.marker({
          lat: b.lat,
          lng: b.lng,
          html: '<span class="pin broker">중</span>',
          title: b.name,
          popup: [b.name, `등록번호 ${b.regNo}`, `전화 ${b.phone}`],
        });
      }
      pts.push(d);
    }
  } else if (mode === 'listing') {
    const called = new Set(visibleListings().map((l) => l.brokerId));
    for (const b of chat?.brokers ?? []) {
      if (!called.has(b.id)) continue;
      p.marker({
        lat: b.lat,
        lng: b.lng,
        html: '<span class="pin broker">중</span>',
        title: b.name,
        popup: [b.name, `등록번호 ${b.regNo}`],
      });
    }
    for (const l of visibleListings()) {
      const tone = PRICE_LABEL[l.priceVerdict].tone;
      p.marker({
        lat: l.lat,
        lng: l.lng,
        html: `<span class="lpin t-${tone}"><b>${l.no}</b>${esc(depRent(l.deposit, l.rent))}</span>`,
        title: `${l.no}번 ${l.building}`,
        popup: [
          `${l.no}. ${l.building}`,
          `${depRent(l.deposit, l.rent)} · 실거래 대비 ${PRICE_LABEL[l.priceVerdict].text}`,
          CONTACT_LABEL[l.contact].text,
        ],
        onClick: () => ui({ mapFocus: l.id, sheetOpen: true }),
      });
      pts.push(l);
    }
  } else {
    const items = routeItems();
    if (items.length > 1)
      p.line(
        items.map((x) => x.l),
        '#c9632a',
      );
    items.forEach(({ v, l }, i) => {
      p.marker({
        lat: l.lat,
        lng: l.lng,
        html: `<span class="lpin k-visit"><b>${i + 1}</b>${esc(hm(v.at))}</span>`,
        title: `${i + 1}번째 방문 ${hm(v.at)} ${l.building}`,
        popup: [`${hm(v.at)} ${l.building}`, CONTACT_LABEL[l.contact].text],
        onClick: () => ui({ mapFocus: l.id, sheetOpen: true }),
      });
      pts.push(l);
    });
  }

  const focused =
    chat?.search?.dongs.find((d) => d.id === focus) ?? chat?.listings.find((l) => l.id === focus) ?? null;
  if (focused) p.center(focused, 15);
  else if (pts.length) p.fit(wp ? [...pts, wp] : pts);
  else p.center(wp ?? SEOUL, 13);
}

/** 다시 그린 뒤 지도 엔진을 붙이고 표시를 맞춰요 */
export function syncMap(): void {
  const el = document.getElementById('bigmap');
  if (!el) {
    if (provider && providerEl && !providerEl.isConnected) {
      provider.destroy();
      provider = null;
      providerEl = null;
      lastSig = '';
    }
    return;
  }
  if (provider && providerEl === el) {
    paint(provider);
    return;
  }
  if (creating) return;
  provider?.destroy();
  provider = null;
  lastSig = '';
  creating = createProvider(el, state.session?.kakaoMapKey ?? '')
    .then((p) => {
      provider = p;
      providerEl = el;
      requestAnimationFrame(() => {
        p.resize();
        paint(p);
      });
      ui({});
    })
    .finally(() => {
      creating = null;
    });
}

window.addEventListener('resize', () => provider?.resize());

const LEGEND_TITLE: Record<MapMode, string> = {
  dong: '살만한 동네 (과거 실거래 기준)',
  listing: '통화로 찾은 방',
  route: '방문 동선',
};

function legend(): TemplateResult {
  const mode = state.ui.mapMode;
  const items: [string, string][] =
    mode === 'dong'
      ? [
          ['dong', '번호 = 채팅 카드 순위'],
          ['broker', '전화할 등록 중개사무소'],
          ['company', '회사(학교)'],
        ]
      : mode === 'listing'
        ? [
            ['listing-ok', '실거래 대비 적정'],
            ['listing-warn', '약간 비쌈'],
            ['listing-bad', '비쌈'],
            ['broker', '통화한 중개사무소'],
          ]
        : [
            ['visit', '방문 순서와 시각'],
            ['company', '회사(학교)'],
          ];
  return html`<div class="map-legend" data-testid="map-legend">
    <strong>${LEGEND_TITLE[mode]}</strong>
    <ul>
      ${items.map(([k, label]) => html`<li><span class="lg lg-${k}"></span>${label}</li>`)}
    </ul>
    <p class="map-src">
      지도: ${provider?.kind === 'kakao' ? '카카오맵' : 'OpenStreetMap(카카오맵을 쓸 수 없는 주소)'} · 위치는
      예시 값
    </p>
  </div>`;
}

function sheet(): TemplateResult | typeof nothing {
  const chat = state.chat;
  const focus = state.ui.mapFocus;
  if (!focus || !chat) return nothing;
  const d = chat.search?.dongs.find((x) => x.id === focus);
  const l = chat.listings.find((x) => x.id === focus);
  if (!d && !l) return nothing;
  const open = state.ui.sheetOpen;
  let startY = 0;
  const onDown = (e: PointerEvent) => {
    startY = e.clientY;
  };
  const onUp = (e: PointerEvent) => {
    const dy = e.clientY - startY;
    if (Math.abs(dy) < 8) ui({ sheetOpen: !open });
    else ui({ sheetOpen: dy < 0 });
  };
  return html`<div class="sheet ${open ? 'open' : ''}" data-testid="map-sheet">
    <button
      class="sheet-handle"
      aria-expanded=${open}
      aria-label=${open ? '정보 접기' : '정보 펼치기'}
      @pointerdown=${onDown}
      @pointerup=${onUp}
    >
      <i></i>
    </button>
    <div class="sheet-body">
      ${
        d
          ? html`<h3>
                ${d.rank}. ${d.name} <span class="muted">${d.gu}${d.station ? ` · ${d.station}역` : ''}</span>
              </h3>
              <dl class="facts">
                <div>
                  <dt>실거래</dt>
                  <dd>
                    계약 ${d.dealCount}건 · 환산월세 ${d.rentRange[0]}~${d.rentRange[1]} · 중간값 ${d.median}
                  </dd>
                </div>
                <div>
                  <dt>출퇴근</dt>
                  <dd>${commuteLabel(d)}</dd>
                </div>
                <div>
                  <dt>버스</dt>
                  <dd>${busLabel(d)}</dd>
                </div>
                <div>
                  <dt>중개사</dt>
                  <dd>${d.brokers.map((b) => b.name).join(', ')}</dd>
                </div>
              </dl>`
          : l
            ? listingCard(l)
            : nothing
      }
    </div>
  </div>`;
}

/** S-10 큰 지도, S-12 모바일 지도 */
export function mapView(): TemplateResult {
  const { mapMode, mapLayers } = state.ui;
  const hasData = Boolean(state.chat?.search);
  const chip = (label: string, on: boolean, onClick: () => void, testid?: string) =>
    html`<button
      class="map-chip ${on ? 'on' : ''}"
      aria-pressed=${on}
      @click=${onClick}
      data-testid=${testid ?? nothing}
    >
      ${label}
    </button>`;
  return html`<div class="bigmap-wrap" data-testid="bigmap">
    <div id="bigmap" class="bigmap" role="region" aria-label="지도"></div>
    <div class="map-tools" role="group" aria-label="지도 보기">
      ${MODES.map((m) =>
        chip(
          m.label,
          mapMode === m.id,
          () => ui({ mapMode: m.id, mapFocus: null, sheetOpen: false }),
          `map-mode-${m.id}`,
        ),
      )}
      <span class="map-sep" aria-hidden="true"></span>
      ${chip('역', mapLayers.stations, () => ui({ mapLayers: { ...mapLayers, stations: !mapLayers.stations } }))}
      ${chip('출근 권역', mapLayers.commuteRange, () =>
        ui({ mapLayers: { ...mapLayers, commuteRange: !mapLayers.commuteRange } }),
      )}
    </div>
    ${hasData ? nothing : html`<p class="map-empty">동네를 찾으면 여기에 동네와 중개사무소가 보여요.</p>`}
    ${state.ui.mapFocus && state.ui.sheetOpen ? nothing : legend()} ${sheet()}
  </div>`;
}
