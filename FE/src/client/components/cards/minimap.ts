import { html, nothing } from 'lit-html';
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

/** 채팅 속 작은 지도(지도 캡처). 실제 지도 위에 번호·이름 핀을 올리고, 누르면 큰 지도로 */
export function miniMap(points: MiniPoint[], opts: { mode: MapMode; route?: boolean; caption: string }) {
  if (!points.length) return nothing;
  const data = JSON.stringify({ points, route: Boolean(opts.route) });
  return html`<figure class="mini">
    <div class="mini-map" data-mini=${data} aria-hidden="true"></div>
    <button
      class="mini-open"
      @click=${() => openPanel('map', { mode: opts.mode, focus: null })}
      aria-label="${opts.caption}. 누르면 큰 지도로 봐요"
    ></button>
    <figcaption>${opts.caption}</figcaption>
  </figure>`;
}
