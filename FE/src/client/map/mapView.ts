import { html, nothing, type TemplateResult } from 'lit-html';
import type { Listing } from '../../shared/types.js';
import { CHECK_LABEL, CONTACT_LABEL } from '../../shared/labels.js';
import { depRent, hm } from '../../shared/format.js';
import { state, ui, type MapMode } from '../store.js';
import { listingCard } from '../components/cards/listing.js';
import { createProvider, esc, SEOUL, type LatLng, type MapProvider } from './provider.js';

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
  return state.meta?.workplaces.find((w) => w.id === id) ?? null;
}

const COMPANY_PIN = `<span class="pin company" aria-hidden="true"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#fff" stroke-width="2"><rect x="5" y="3.5" width="14" height="17" rx="1.5"/><path d="M9 8h2M13 8h2M9 12h2M13 12h2"/></svg></span>`;

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
      html: COMPANY_PIN,
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
        html: `<span class="pin dong">${d.rank}</span>`,
        title: `${d.rank}순위 ${d.name}`,
        popup: [
          `${d.rank}. ${d.name}`,
          `출퇴근 ${d.commute.minutes}분 · 환승 ${d.commute.transfers}회`,
          `환산월세 중간값 ${d.median}만 원`,
        ],
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
      const tone = CHECK_LABEL[l.check].tone;
      p.marker({
        lat: l.lat,
        lng: l.lng,
        html: `<span class="pin listing t-${tone}">${l.no}</span>`,
        title: `${l.no}번 ${l.building}`,
        popup: [
          `${l.no}. ${l.building}`,
          `${depRent(l.deposit, l.rent)} · ${CHECK_LABEL[l.check].text}`,
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
        html: `<span class="pin visit"><b>${i + 1}</b>${esc(hm(v.at))}</span>`,
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

function legend(): TemplateResult {
  const mode = state.ui.mapMode;
  const items: [string, string][] =
    mode === 'dong'
      ? [
          ['dong', '살만한 동네(번호 = 순위)'],
          ['broker', '전화할 중개사무소'],
          ['company', '회사(학교)'],
        ]
      : mode === 'listing'
        ? [
            ['listing ok', '추천'],
            ['listing warn', '주의'],
            ['listing bad', '제외 권장'],
            ['listing muted', '등기 대기'],
            ['broker', '통화한 중개사무소'],
          ]
        : [
            ['visit', '방문 순서와 시각'],
            ['company', '회사(학교)'],
          ];
  return html`<ul class="map-legend">
    ${items.map(([k, label]) => html`<li><span class="lg lg-${k.replace(' ', '-')}"></span>${label}</li>`)}
  </ul>`;
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
          ? html`<h3>${d.rank}. ${d.name} <span class="muted">${d.gu} · ${d.station}역</span></h3>
              <dl class="facts">
                <div>
                  <dt>실거래</dt>
                  <dd>
                    계약 ${d.dealCount}건 · 환산월세 ${d.rentRange[0]}~${d.rentRange[1]} · 중간값 ${d.median}
                  </dd>
                </div>
                <div>
                  <dt>출퇴근</dt>
                  <dd>${d.commute.minutes}분 · 환승 ${d.commute.transfers}회</dd>
                </div>
                <div>
                  <dt>버스</dt>
                  <dd>${d.bus.route}번 배차 ${d.bus.interval}분 · 막차 ${d.bus.last}</dd>
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
  return html`<div class="bigmap-wrap" data-testid="bigmap">
    <div class="map-tools">
      <div class="seg-btns" role="group" aria-label="지도 보기">
        ${MODES.map(
          (m) =>
            html`<button
              class="seg-btn small"
              aria-pressed=${mapMode === m.id}
              @click=${() => ui({ mapMode: m.id, mapFocus: null, sheetOpen: false })}
            >
              ${m.label}
            </button>`,
        )}
      </div>
      <div class="checks layers">
        <label
          ><input
            type="checkbox"
            .checked=${mapLayers.stations}
            @change=${(e: Event) => ui({ mapLayers: { ...mapLayers, stations: (e.target as HTMLInputElement).checked } })}
          />
          역</label
        >
        <label
          ><input
            type="checkbox"
            .checked=${mapLayers.commuteRange}
            @change=${(e: Event) => ui({ mapLayers: { ...mapLayers, commuteRange: (e.target as HTMLInputElement).checked } })}
          />
          출근 권역</label
        >
      </div>
    </div>
    <div id="bigmap" class="bigmap" role="region" aria-label="지도"></div>
    ${hasData ? nothing : html`<p class="map-empty">동네를 찾으면 여기에 동네와 중개사무소가 보여요.</p>`}
    ${legend()}
    <p class="map-src">
      지도 ${provider?.kind === 'kakao' ? '카카오맵' : 'OpenStreetMap(카카오맵을 쓸 수 없는 주소)'} · 위치는
      예시 값
    </p>
    ${sheet()}
  </div>`;
}
