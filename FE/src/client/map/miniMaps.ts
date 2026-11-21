/* 채팅 카드 안의 작은 지도들. 다시 그린 뒤 새로 생긴 칸에만 지도를 붙이고, 사라진 칸의 지도는 정리해요. */
import type { MiniPoint } from '../components/cards/minimap.js';
import { state } from '../store.js';
import { createProvider, esc, type MapProvider } from './provider.js';
import { COMPANY_ICON } from './pins.js';

const live = new Map<HTMLElement, { provider: MapProvider | null; data: string }>();

function pinHtml(p: MiniPoint): string {
  if (p.kind === 'company') return `<span class="lpin k-company">${COMPANY_ICON}${esc(p.label)}</span>`;
  if (p.kind === 'visit') return `<span class="lpin k-visit">${esc(p.label)}</span>`;
  const no = p.sub ? `<b>${esc(p.sub)}</b>` : '';
  const tone = p.kind === 'dong' ? (p.sub === '1' ? 'k-first' : 'k-dong') : `t-${p.tone ?? 'muted'}`;
  return `<span class="lpin ${tone}">${no}${esc(p.label)}</span>`;
}

async function attach(el: HTMLElement, data: string): Promise<void> {
  const entry = { provider: null as MapProvider | null, data };
  live.set(el, entry);
  const { points, route } = JSON.parse(data) as { points: MiniPoint[]; route: boolean };
  const p = await createProvider(el, state.session?.kakaoMapKey ?? '', false);
  if (!el.isConnected) {
    p.destroy();
    return;
  }
  entry.provider = p;
  requestAnimationFrame(() => {
    p.resize();
    if (route) {
      const visits = points.filter((x) => x.kind === 'visit');
      if (visits.length > 1) p.line(visits, '#c9632a');
    }
    for (const pt of points) p.marker({ lat: pt.lat, lng: pt.lng, html: pinHtml(pt), title: pt.label });
    p.fit(points, 14);
  });
}

export function syncMiniMaps(): void {
  for (const [el, entry] of live) {
    if (!el.isConnected) {
      entry.provider?.destroy();
      live.delete(el);
    }
  }
  for (const el of document.querySelectorAll<HTMLElement>('.mini-map')) {
    const data = el.dataset.mini ?? '';
    const cur = live.get(el);
    if (cur && cur.data === data) continue;
    if (cur) {
      cur.provider?.destroy();
      el.replaceChildren();
    }
    void attach(el, data);
  }
}
