import { html } from 'lit-html';
import type { CondValues, Conditions } from '../../shared/types.js';
import { act, state } from '../store.js';

function val<K extends keyof Conditions>(c: Conditions, k: K): unknown {
  return c[k]?.value;
}

/** 조건 양식: [조건 골라서 찾기], 조건 카드의 [조건 고치기], 내 조건의 [조건 바꾸기]가 같은 양식을 써요. */
export function condFormView(opts: {
  id: string;
  submitLabel: string;
  onDone?: () => void;
  autofocus?: boolean;
}) {
  const c = state.chat?.conditions ?? {};
  const wps = state.meta?.workplaces ?? [];
  // 회사 목록에 있는 이름이면 그 id, 아니면 적은 이름 그대로(서버가 카카오 장소 검색으로 위치를 찾아요)
  const toWorkplace = (text: string) => {
    const t = text.trim();
    if (!t) return null;
    return wps.find((w) => w.name === t || w.id === t)?.id ?? t.slice(0, 40);
  };
  const wpText = (v: string) => wps.find((w) => w.id === v)?.name ?? v;
  const onSubmit = async (e: Event) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget as HTMLFormElement);
    const num = (k: string) => {
      const v = String(f.get(k) ?? '').trim();
      return v === '' ? undefined : Number(v);
    };
    const nullable = (k: string) => {
      const v = String(f.get(k) ?? '');
      return v === '' ? null : Number(v);
    };
    const list = (k: string) =>
      String(f.get(k) ?? '')
        .split(/[,，、]/)
        .map((x) => x.trim())
        .filter(Boolean)
        .slice(0, 10);
    const checked = <T extends string>(k: string) => f.getAll(k).map(String) as T[];
    const values: Partial<CondValues> = {
      workplace: toWorkplace(String(f.get('workplace') ?? '')),
      rent: num('rent') ?? null,
      deposit: num('deposit'),
      maxCommute: num('maxCommute'),
      maxTransfer: num('maxTransfer'),
      maxBusInterval: nullable('maxBusInterval'),
      builtAfter: nullable('builtAfter'),
      houseType: f.get('houseType') as CondValues['houseType'],
      priceBand: f.get('priceBand') as CondValues['priceBand'],
      priority: checked<CondValues['priority'][number]>('priority'),
      leaseTypes: checked<CondValues['leaseTypes'][number]>('leaseTypes'),
      preferredAreas: list('preferredAreas'),
      avoidAreas: list('avoidAreas'),
      minArea: nullable('minArea'),
      minFloor: nullable('minFloor'),
      maxWalk: nullable('maxWalk'),
    };
    const jeonseOnly = !!values.leaseTypes?.length && values.leaseTypes.every((l) => l === 'jeonse');
    const form = e.currentTarget as HTMLFormElement;
    const err = form.querySelector<HTMLElement>('.form-error');
    if (!values.workplace) {
      if (err) err.textContent = '회사(학교) 위치를 적어 주세요.';
      form.querySelector<HTMLInputElement>('input[name=workplace]')?.focus({ preventScroll: true });
      return;
    }
    if (!values.leaseTypes?.length) {
      if (err) err.textContent = '계약 유형을 하나 이상 골라 주세요.';
      return;
    }
    if (!jeonseOnly && (values.rent === null || values.rent === undefined)) {
      if (err) err.textContent = '월세 예산을 적어 주세요.';
      form.querySelector<HTMLInputElement>('input[name=rent]')?.focus({ preventScroll: true });
      return;
    }
    if (err) err.textContent = '';
    // 기본값과 같은 '상관없음'은 보내지 않아요(말씀하신 조건으로 남지 않게).
    for (const [k, v] of Object.entries(values)) {
      if (
        v === undefined ||
        v === 'any' ||
        (v === null && k !== 'workplace') ||
        (Array.isArray(v) && v.length === 0) ||
        (k === 'leaseTypes' && Array.isArray(v) && v.length === 1 && v[0] === 'monthly')
      ) {
        delete (values as Record<string, unknown>)[k];
      }
    }
    if (await act({ type: 'submitCondForm', values })) opts.onDone?.();
  };
  const sel = (name: string, current: unknown, options: [string, string][]) =>
    html`<select name=${name} id=${`${opts.id}-${name}`}>
      ${options.map(([v, label]) => html`<option value=${v} ?selected=${String(current ?? '') === v}>${label}</option>`)}
    </select>`;
  return html`<form class="cond-form" @submit=${onSubmit} novalidate data-testid="cond-form">
    <div class="grid">
      <label for=${`${opts.id}-workplace`}>회사(학교) <em>필수</em></label>
      <input
        name="workplace"
        id=${`${opts.id}-workplace`}
        list=${`${opts.id}-workplaces`}
        placeholder="예) 강남역, 서울대, 회사 이름"
        maxlength="40"
        autocomplete="off"
        .value=${wpText(String(val(c, 'workplace') ?? ''))}
        ?autofocus=${opts.autofocus}
        required
      />
      <datalist id=${`${opts.id}-workplaces`}>
        ${wps.map((w) => html`<option value=${w.name}></option>`)}
      </datalist>
      <span class="label">계약 유형 <em>필수</em></span>
      <div class="checks">
        ${(
          [
            ['monthly', '월세'],
            ['jeonse', '전세'],
            ['semi_jeonse', '반전세'],
          ] as const
        ).map(
          ([v, label]) =>
            html`<label
              ><input
                type="checkbox"
                name="leaseTypes"
                value=${v}
                ?checked=${((val(c, 'leaseTypes') as string[] | undefined) ?? ['monthly']).includes(v)}
              />
              ${label}</label
            >`,
        )}
      </div>
      <label for=${`${opts.id}-rent`}>월세 상한(만 원) <em>전세만이면 비워도 돼요</em></label>
      <input
        name="rent"
        id=${`${opts.id}-rent`}
        type="number"
        inputmode="numeric"
        min="10"
        max="300"
        step="5"
        .value=${String(val(c, 'rent') ?? '')}
        placeholder="예: 60"
      />
      <label for=${`${opts.id}-deposit`}>보증금 상한(만 원)</label>
      <input
        name="deposit"
        id=${`${opts.id}-deposit`}
        type="number"
        inputmode="numeric"
        min="0"
        max="50000"
        step="100"
        .value=${String(val(c, 'deposit') ?? '')}
        placeholder="비우면 1,000"
      />
      <label for=${`${opts.id}-houseType`}>유형</label>
      ${sel('houseType', val(c, 'houseType') ?? 'any', [
        ['any', '상관없음'],
        ['villa', '원룸·빌라'],
        ['officetel', '오피스텔'],
      ])}
      <label for=${`${opts.id}-builtAfter`}>준공</label>
      ${sel('builtAfter', val(c, 'builtAfter') ?? '', [
        ['', '상관없음'],
        ['2010', '2010년 이후'],
        ['2015', '2015년 이후'],
        ['2020', '2020년 이후'],
      ])}
      <label for=${`${opts.id}-maxCommute`}>출퇴근</label>
      ${sel('maxCommute', val(c, 'maxCommute') ?? '', [
        ['', '비우면 40분'],
        ['30', '30분 이내'],
        ['40', '40분 이내'],
        ['50', '50분 이내'],
        ['60', '60분 이내'],
      ])}
      <label for=${`${opts.id}-maxTransfer`}>환승</label>
      ${sel('maxTransfer', val(c, 'maxTransfer') ?? '', [
        ['', '비우면 1회 이하'],
        ['0', '환승 없이'],
        ['1', '1회 이하'],
        ['2', '2회 이하'],
      ])}
      <label for=${`${opts.id}-maxBusInterval`}>버스 배차</label>
      ${sel('maxBusInterval', val(c, 'maxBusInterval') ?? '', [
        ['', '상관없음'],
        ['5', '5분 이하'],
        ['10', '10분 이하'],
        ['15', '15분 이하'],
      ])}
      <label for=${`${opts.id}-maxWalk`}>역까지 도보</label>
      ${sel('maxWalk', val(c, 'maxWalk') ?? '', [
        ['', '상관없음'],
        ['5', '5분 이내'],
        ['10', '10분 이내'],
        ['15', '15분 이내'],
      ])}
      <label for=${`${opts.id}-preferredAreas`}>살 곳</label>
      <input
        name="preferredAreas"
        id=${`${opts.id}-preferredAreas`}
        maxlength="120"
        placeholder="예) 마포구, 서교동 (쉼표로 여러 곳)"
        .value=${((val(c, 'preferredAreas') as string[] | undefined) ?? []).join(', ')}
      />
      <label for=${`${opts.id}-avoidAreas`}>피할 곳</label>
      <input
        name="avoidAreas"
        id=${`${opts.id}-avoidAreas`}
        maxlength="120"
        placeholder="예) 신림동 (쉼표로 여러 곳)"
        .value=${((val(c, 'avoidAreas') as string[] | undefined) ?? []).join(', ')}
      />
      <label for=${`${opts.id}-minArea`}>최소 면적(㎡)</label>
      <input
        name="minArea"
        id=${`${opts.id}-minArea`}
        type="number"
        inputmode="numeric"
        min="10"
        max="200"
        step="1"
        .value=${String(val(c, 'minArea') ?? '')}
        placeholder="상관없음"
      />
      <label for=${`${opts.id}-minFloor`}>최소 층</label>
      ${sel('minFloor', val(c, 'minFloor') ?? '', [
        ['', '상관없음'],
        ['1', '1층 이상(반지하 제외)'],
        ['2', '2층 이상'],
        ['3', '3층 이상'],
      ])}
      <label for=${`${opts.id}-priceBand`}>가격 구간</label>
      ${sel('priceBand', val(c, 'priceBand') ?? 'any', [
        ['any', '상관없음'],
        ['low', '시세 중앙값 이하'],
      ])}
      <span class="label">우선순위</span>
      <div class="checks">
        ${(
          [
            ['price', '가격'],
            ['commute', '출퇴근'],
            ['bus_headway', '버스 배차'],
            ['building_age', '신축'],
            ['area', '면적'],
          ] as const
        ).map(
          ([v, label]) =>
            html`<label
              ><input
                type="checkbox"
                name="priority"
                value=${v}
                ?checked=${((val(c, 'priority') as string[] | undefined) ?? []).includes(v)}
              />
              ${label}</label
            >`,
        )}
      </div>
    </div>
    <p class="form-error" role="alert"></p>
    <div class="actions">
      <button class="btn-primary" type="submit" ?disabled=${state.pending} data-testid="cond-form-submit">
        ${opts.submitLabel}
      </button>
      ${opts.onDone ? html`<button class="btn-ghost" type="button" @click=${opts.onDone}>닫기</button>` : ''}
    </div>
  </form>`;
}
