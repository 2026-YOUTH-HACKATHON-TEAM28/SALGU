import { html, svg, nothing } from 'lit-html';
import type { Tone } from '../../../shared/labels.js';
import { openPanel, type MapMode } from '../../store.js';

export interface MiniPoint {
  lat: number;
  lng: number;
  label: string;
  kind: 'dong' | 'company' | 'listing' | 'visit';
  tone?: Tone;
  sub?: string;
}

const W = 320;
const H = 170;
const PAD = 26;

/** 채팅 속 작은 지도(지도 캡처). 누르면 큰 지도로 */
export function miniMap(points: MiniPoint[], opts: { mode: MapMode; route?: boolean; caption: string }) {
  if (!points.length) return nothing;
  const lats = points.map((p) => p.lat);
  const lngs = points.map((p) => p.lng);
  let [minLat, maxLat, minLng, maxLng] = [
    Math.min(...lats),
    Math.max(...lats),
    Math.min(...lngs),
    Math.max(...lngs),
  ];
  // 너무 좁으면 넓혀서 핀이 겹치지 않게
  const spanLat = Math.max(maxLat - minLat, 0.01);
  const spanLng = Math.max(maxLng - minLng, 0.012);
  const cLat = (minLat + maxLat) / 2;
  const cLng = (minLng + maxLng) / 2;
  minLat = cLat - spanLat / 2;
  maxLat = cLat + spanLat / 2;
  minLng = cLng - spanLng / 2;
  maxLng = cLng + spanLng / 2;
  const sx = (W - PAD * 2) / (maxLng - minLng);
  const sy = (H - PAD * 2) / (maxLat - minLat);
  const s = Math.min(sx, sy * 1.25);
  const ox = (W - (maxLng - minLng) * s) / 2;
  const oy = (H - (maxLat - minLat) * (s / 1.25)) / 2;
  const x = (lng: number) => ox + (lng - minLng) * s;
  const y = (lat: number) => H - (oy + (lat - minLat) * (s / 1.25));
  const route = opts.route ? points.filter((p) => p.kind === 'visit') : [];

  return html`<button
    class="minimap"
    @click=${() => openPanel('map', { mode: opts.mode, focus: null })}
    aria-label="${opts.caption}. 누르면 큰 지도로 봐요"
  >
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-hidden="true">
      <rect width=${W} height=${H} rx="10" class="mm-bg" />
      ${[1, 2, 3].map((i) => svg`<line x1=${(W / 4) * i} y1="0" x2=${(W / 4) * i} y2=${H} class="mm-grid" />`)}
      ${[1, 2].map((i) => svg`<line x1="0" y1=${(H / 3) * i} x2=${W} y2=${(H / 3) * i} class="mm-grid" />`)}
      ${
        route.length > 1
          ? svg`<polyline class="mm-route" points=${route.map((p) => `${x(p.lng)},${y(p.lat)}`).join(' ')} />`
          : nothing
      }
      ${points.map((p) => {
        const px = x(p.lng);
        const py = y(p.lat);
        if (p.kind === 'company') {
          return svg`<g class="mm-company"><rect x=${px - 9} y=${py - 9} width="18" height="18" rx="4"/><path d=${`M${px - 4} ${py - 3}h3M${px + 1} ${py - 3}h3M${px - 4} ${py + 1}h3M${px + 1} ${py + 1}h3`} /><text x=${px} y=${py + 21}>${p.label}</text></g>`;
        }
        if (p.kind === 'dong') {
          return svg`<g class="mm-dong"><circle cx=${px} cy=${py} r="20" class="mm-area"/><circle cx=${px} cy=${py} r="10" class="mm-pin"/><text x=${px} y=${py + 4} class="mm-no">${p.sub ?? ''}</text><text x=${px} y=${py + 32}>${p.label}</text></g>`;
        }
        return svg`<g class="mm-listing tone-${p.tone ?? 'muted'}"><circle cx=${px} cy=${py} r="9" class="mm-pin"/><text x=${px} y=${py + 3.5} class="mm-no">${p.sub ?? ''}</text>${
          p.label ? svg`<text x=${px} y=${py + 21}>${p.label}</text>` : nothing
        }</g>`;
      })}
    </svg>
    <span class="minimap-cap">${opts.caption} · 크게 보기</span>
  </button>`;
}
