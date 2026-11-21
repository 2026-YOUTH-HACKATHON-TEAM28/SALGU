/* 지도 엔진을 감싼 얇은 층. 카카오맵을 먼저 쓰고, 키가 없거나 불러오지 못하면 OpenStreetMap(Leaflet)으로 대체해요. */
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';

export interface LatLng {
  lat: number;
  lng: number;
}

export interface MarkerSpec extends LatLng {
  /** 마커 모양(HTML, 안전한 값만) */
  html: string;
  title: string;
  /** 누르면 보일 설명(글자만, HTML 아님) */
  popup?: string[];
  onClick?: () => void;
}

export interface MapProvider {
  readonly kind: 'kakao' | 'osm';
  clear(): void;
  marker(m: MarkerSpec): void;
  circle(c: LatLng & { radius: number; color: string; dashed?: boolean }): void;
  line(points: LatLng[], color: string): void;
  fit(points: LatLng[], maxZoom?: number): void;
  center(p: LatLng, zoom: number): void;
  resize(): void;
  destroy(): void;
}

export const SEOUL: LatLng = { lat: 37.495, lng: 126.95 };

export function esc(s: string): string {
  return s.replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] as string,
  );
}

function popupHtml(lines: string[]): string {
  return lines.map((l, i) => (i === 0 ? `<strong>${esc(l)}</strong>` : `<div>${esc(l)}</div>`)).join('');
}

/* ---------- OpenStreetMap (Leaflet) ---------- */

class OsmProvider implements MapProvider {
  readonly kind = 'osm' as const;
  private map: L.Map;
  private layer: L.LayerGroup;

  constructor(el: HTMLElement) {
    this.map = L.map(el, { zoomControl: true, attributionControl: true, minZoom: 10, maxZoom: 18 }).setView(
      [SEOUL.lat, SEOUL.lng],
      13,
    );
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
      maxZoom: 19,
      // OSM 타일 이용 정책: 출처를 보내야 해요(없으면 403 Access denied)
      referrerPolicy: 'strict-origin-when-cross-origin',
    }).addTo(this.map);
    this.layer = L.layerGroup().addTo(this.map);
  }
  clear() {
    this.layer.clearLayers();
  }
  marker(m: MarkerSpec) {
    const mk = L.marker([m.lat, m.lng], {
      icon: L.divIcon({ html: m.html, className: 'pin-wrap', iconSize: undefined }),
      title: m.title,
      keyboard: true,
    });
    if (m.popup) mk.bindPopup(popupHtml(m.popup));
    if (m.onClick) mk.on('click', m.onClick);
    mk.addTo(this.layer);
  }
  circle(c: LatLng & { radius: number; color: string; dashed?: boolean }) {
    L.circle([c.lat, c.lng], {
      radius: c.radius,
      color: c.color,
      weight: 1.5,
      fillOpacity: 0.12,
      dashArray: c.dashed ? '6 6' : undefined,
    }).addTo(this.layer);
  }
  line(points: LatLng[], color: string) {
    L.polyline(
      points.map((p) => [p.lat, p.lng] as [number, number]),
      { color, weight: 3, dashArray: '8 8' },
    ).addTo(this.layer);
  }
  fit(points: LatLng[], maxZoom = 15) {
    if (!points.length) return;
    this.map.fitBounds(L.latLngBounds(points.map((p) => [p.lat, p.lng] as [number, number])), {
      padding: [36, 36],
      maxZoom,
    });
  }
  center(p: LatLng, zoom: number) {
    this.map.setView([p.lat, p.lng], zoom);
  }
  resize() {
    this.map.invalidateSize();
  }
  destroy() {
    this.map.remove();
  }
}

/* ---------- 카카오맵 ---------- */

/* 카카오맵 SDK 의 필요한 부분만 적은 타입 */
interface KakaoMaps {
  load(cb: () => void): void;
  LatLng: new (lat: number, lng: number) => unknown;
  LatLngBounds: new () => { extend(p: unknown): void };
  Map: new (el: HTMLElement, opts: { center: unknown; level: number }) => KakaoMap;
  CustomOverlay: new (opts: {
    position: unknown;
    content: HTMLElement;
    yAnchor?: number;
    clickable?: boolean;
  }) => KakaoObj;
  Circle: new (opts: Record<string, unknown>) => KakaoObj;
  Polyline: new (opts: Record<string, unknown>) => KakaoObj;
  ZoomControl: new () => unknown;
  ControlPosition: { RIGHT: unknown };
}
interface KakaoMap {
  setBounds(b: unknown, ...pad: number[]): void;
  setCenter(p: unknown): void;
  setLevel(l: number): void;
  getLevel(): number;
  relayout(): void;
  addControl(c: unknown, pos: unknown): void;
}
interface KakaoObj {
  setMap(m: KakaoMap | null): void;
}

declare global {
  interface Window {
    kakao?: { maps: KakaoMaps };
  }
}

let kakaoLoad: Promise<KakaoMaps> | null = null;

function loadKakao(key: string): Promise<KakaoMaps> {
  if (kakaoLoad) return kakaoLoad;
  kakaoLoad = new Promise<KakaoMaps>((resolve, reject) => {
    const s = document.createElement('script');
    s.src = `https://dapi.kakao.com/v2/maps/sdk.js?appkey=${encodeURIComponent(key)}&autoload=false`;
    s.async = true;
    const timer = window.setTimeout(() => reject(new Error('timeout')), 6000);
    s.onload = () => {
      const maps = window.kakao?.maps;
      if (!maps) return reject(new Error('no kakao'));
      maps.load(() => {
        window.clearTimeout(timer);
        resolve(maps);
      });
    };
    s.onerror = () => {
      window.clearTimeout(timer);
      reject(new Error('load failed'));
    };
    document.head.appendChild(s);
  });
  return kakaoLoad;
}

class KakaoProvider implements MapProvider {
  readonly kind = 'kakao' as const;
  private map: KakaoMap;
  private objs: KakaoObj[] = [];
  private popup: KakaoObj | null = null;

  constructor(
    private readonly k: KakaoMaps,
    el: HTMLElement,
  ) {
    this.map = new k.Map(el, { center: new k.LatLng(SEOUL.lat, SEOUL.lng), level: 6 });
    this.map.addControl(new k.ZoomControl(), k.ControlPosition.RIGHT);
  }
  private add(o: KakaoObj) {
    o.setMap(this.map);
    this.objs.push(o);
  }
  clear() {
    for (const o of this.objs) o.setMap(null);
    this.objs = [];
    this.popup?.setMap(null);
  }
  marker(m: MarkerSpec) {
    const el = document.createElement('button');
    el.className = 'pin-wrap';
    el.type = 'button';
    el.title = m.title;
    el.setAttribute('aria-label', m.title);
    el.innerHTML = m.html;
    const pos = new this.k.LatLng(m.lat, m.lng);
    el.addEventListener('click', () => {
      m.onClick?.();
      if (m.popup) {
        this.popup?.setMap(null);
        const box = document.createElement('div');
        box.className = 'kakao-pop';
        box.innerHTML = popupHtml(m.popup);
        this.popup = new this.k.CustomOverlay({ position: pos, content: box, yAnchor: 1.6 });
        this.popup.setMap(this.map);
      }
    });
    this.add(new this.k.CustomOverlay({ position: pos, content: el, yAnchor: 0.5, clickable: true }));
  }
  circle(c: LatLng & { radius: number; color: string; dashed?: boolean }) {
    this.add(
      new this.k.Circle({
        center: new this.k.LatLng(c.lat, c.lng),
        radius: c.radius,
        strokeWeight: 1.5,
        strokeColor: c.color,
        strokeStyle: c.dashed ? 'dash' : 'solid',
        fillColor: c.color,
        fillOpacity: 0.12,
      }),
    );
  }
  line(points: LatLng[], color: string) {
    this.add(
      new this.k.Polyline({
        path: points.map((p) => new this.k.LatLng(p.lat, p.lng)),
        strokeWeight: 3,
        strokeColor: color,
        strokeStyle: 'dash',
      }),
    );
  }
  fit(points: LatLng[]) {
    if (!points.length) return;
    const b = new this.k.LatLngBounds();
    for (const p of points) b.extend(new this.k.LatLng(p.lat, p.lng));
    this.map.setBounds(b, 40, 40, 40, 40);
    if (this.map.getLevel() < 4) this.map.setLevel(4);
  }
  center(p: LatLng, zoom: number) {
    this.map.setCenter(new this.k.LatLng(p.lat, p.lng));
    this.map.setLevel(Math.max(1, 19 - zoom));
  }
  resize() {
    this.map.relayout();
  }
  destroy() {
    this.clear();
  }
}

let kakaoFailed = false;

/** 지도 만들기: 카카오 키가 있으면 카카오맵, 안 되면 OpenStreetMap */
export async function createProvider(el: HTMLElement, kakaoKey: string): Promise<MapProvider> {
  if (kakaoKey && !kakaoFailed) {
    try {
      const k = await loadKakao(kakaoKey);
      return new KakaoProvider(k, el);
    } catch {
      kakaoFailed = true;
    }
  }
  return new OsmProvider(el);
}
