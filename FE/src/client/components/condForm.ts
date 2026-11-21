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
    const values: Partial<CondValues> = {
      workplace: String(f.get('workplace') ?? '') || null,
      rent: num('rent') ?? null,
      deposit: num('deposit'),
      maxCommute: num('maxCommute'),
      maxTransfer: num('maxTransfer'),
      maxBusInterval: nullable('maxBusInterval'),
      builtAfter: nullable('builtAfter'),
      houseType: f.get('houseType') as CondValues['houseType'],
      priceBand: f.get('priceBand') as CondValues['priceBand'],
      priority: f.get('priority') as CondValues['priority'],
      commercial: f.get('commercial') as CondValues['commercial'],
      pet: f.get('pet') === 'on',
      parking: f.get('parking') === 'on',
    };
    const form = e.currentTarget as HTMLFormElement;
    const err = form.querySelector<HTMLElement>('.form-error');
    if (!values.workplace) {
      if (err) err.textContent = '회사(학교) 위치를 골라 주세요.';
      form.querySelector<HTMLSelectElement>('select[name=workplace]')?.focus();
      return;
    }
    if (values.rent === null || values.rent === undefined) {
      if (err) err.textContent = '월세 예산을 적어 주세요.';
      form.querySelector<HTMLInputElement>('input[name=rent]')?.focus();
      return;
    }
    if (err) err.textContent = '';
    // 기본값과 같은 '상관없음'은 보내지 않아요(말씀하신 조건으로 남지 않게).
    for (const [k, v] of Object.entries(values)) {
      if (
        v === undefined ||
        v === 'any' ||
        (v === null && k !== 'workplace') ||
        v === false ||
        (k === 'priority' && v === 'balanced')
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
      <select name="workplace" id=${`${opts.id}-workplace`} ?autofocus=${opts.autofocus} required>
        <option value="">고르기</option>
        ${wps.map((w) => html`<option value=${w.id} ?selected=${val(c, 'workplace') === w.id}>${w.name}</option>`)}
      </select>
      <label for=${`${opts.id}-rent`}>월세 상한(만 원) <em>필수</em></label>
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
      <label for=${`${opts.id}-priceBand`}>가격 구간</label>
      ${sel('priceBand', val(c, 'priceBand') ?? 'any', [
        ['any', '상관없음'],
        ['low', '싼 편(하위 30%)'],
        ['mid', '중간(30~70%)'],
      ])}
      <label for=${`${opts.id}-priority`}>우선순위</label>
      ${sel('priority', val(c, 'priority') ?? 'balanced', [
        ['balanced', '고르게'],
        ['commute', '출퇴근 먼저'],
        ['price', '가격 먼저'],
        ['new', '새 집 먼저'],
      ])}
      <label for=${`${opts.id}-commercial`}>상권</label>
      ${sel('commercial', val(c, 'commercial') ?? 'any', [
        ['any', '상관없음'],
        ['lively', '번화한 곳'],
        ['quiet', '조용한 주택가'],
      ])}
      <span class="label">그 밖에</span>
      <div class="checks">
        <label><input type="checkbox" name="pet" ?checked=${val(c, 'pet') === true} /> 반려동물</label>
        <label><input type="checkbox" name="parking" ?checked=${val(c, 'parking') === true} /> 주차</label>
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
