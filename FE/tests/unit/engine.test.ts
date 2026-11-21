import { describe, expect, it } from 'vitest';
import {
  convRent,
  judge,
  median,
  priceVerdict,
  searchDongs,
  valuesOf,
  type RegistryFacts,
} from '../../src/server/mock/engine.js';
import { WORKPLACES, dealsOf } from '../../src/server/mock/data.js';
import type { Conditions } from '../../src/shared/types.js';

const said = <T>(value: T) => ({ value, source: 'said' as const });

describe('환산월세', () => {
  it('보증금 1,000만 원, 월세 50만 원, 전환율 5% 이면 54.2만 원', () => {
    expect(convRent(1000, 50)).toBeCloseTo(54.1667, 3);
  });
  it('전환율을 바꿔 계산할 수 있어요', () => {
    expect(convRent(1200, 40, 6)).toBe(46);
  });
});

describe('중간값', () => {
  it('홀수·짝수 개수', () => {
    expect(median([3, 1, 2])).toBe(2);
    expect(median([4, 1, 2, 3])).toBe(2.5);
    expect(median([])).toBe(0);
  });
});

describe('조건 값', () => {
  it('말하지 않은 칸은 기본값', () => {
    const v = valuesOf({ rent: said(55) });
    expect(v.rent).toBe(55);
    expect(v.maxCommute).toBe(40);
    expect(v.deposit).toBe(1000);
  });
});

describe('동네 찾기', () => {
  const conds: Conditions = { workplace: said('yeouido'), rent: said(60) };

  it('여의도, 월세 60만 원이면 3곳을 점수 순으로', () => {
    const r = searchDongs(conds, WORKPLACES);
    expect(r.dongs).toHaveLength(3);
    expect(r.dongs.map((d) => d.rank)).toEqual([1, 2, 3]);
    for (let i = 1; i < r.dongs.length; i++) {
      expect(r.dongs[i - 1]!.score).toBeGreaterThanOrEqual(r.dongs[i]!.score);
    }
    for (const d of r.dongs) {
      expect(d.commute.minutes).toBeLessThanOrEqual(40);
      expect(d.brokers).toHaveLength(3);
      expect(d.rentRange[0]).toBeLessThanOrEqual(d.median);
      expect(d.median).toBeLessThanOrEqual(d.rentRange[1]);
    }
  });

  it('결과가 매번 같아요(결정적)', () => {
    expect(searchDongs(conds, WORKPLACES)).toEqual(searchDongs(conds, WORKPLACES));
  });

  it('조건이 너무 좁으면 0곳과 걸러 낸 이유', () => {
    const r = searchDongs({ workplace: said('gangnam'), rent: said(20), maxCommute: said(15) }, WORKPLACES);
    expect(r.dongs).toHaveLength(0);
    expect(r.losses.length).toBeGreaterThan(0);
    expect(r.losses[0]!.count).toBeGreaterThan(0);
  });

  it('회사가 없으면 찾지 않아요', () => {
    expect(searchDongs({ rent: said(60) }, WORKPLACES).dongs).toHaveLength(0);
  });

  it('제외한 동네는 다시 나오지 않아요', () => {
    const first = searchDongs(conds, WORKPLACES);
    const next = searchDongs(
      conds,
      WORKPLACES,
      first.dongs.map((d) => d.id),
    );
    for (const d of next.dongs) expect(first.dongs.map((x) => x.id)).not.toContain(d.id);
  });
});

describe('시세 판정', () => {
  it('같은 조건 중간값보다 훨씬 비싸면 비쌈, 싸면 적정', () => {
    const d = dealsOf('bongcheon').find((x) => x.type === 'villa')!;
    expect(priceVerdict('bongcheon', d.area, 'villa', 1000, 200)).toBe('high');
    expect(priceVerdict('bongcheon', d.area, 'villa', 500, 20)).toBe('fair');
  });
});

describe('등기·대출 판정 (r1-2026-11)', () => {
  const base: RegistryFacts = {
    address: '서울 관악구 봉천동 1-1 101호',
    owner: '김**',
    owners: 1,
    mortgage: 3000,
    seizure: false,
    trust: false,
    leaseRight: false,
    buildingUse: '다세대주택',
    violation: false,
    approvedYear: 2015,
    area: 24,
    salePrice: 30000,
    deposit: 1000,
  };

  it('대출 가능 + 비율 낮음 = 추천', () => {
    const j = judge(base);
    expect(j.status).toBe('recommend');
    expect(j.ratio).toBeCloseTo(13.3, 1);
    expect(j.loanOk).toBe(true);
  });
  it('비율 70~80% = 주의', () => {
    expect(judge({ ...base, mortgage: 21000 }).status).toBe('caution');
  });
  it('비율 80% 이상 = 제외 권장', () => {
    const j = judge({ ...base, mortgage: 24000 });
    expect(j.risk).toBe('danger');
    expect(j.status).toBe('exclude');
  });
  it('근린생활시설·위반건축물·85㎡ 초과는 대출 불가로 제외 권장', () => {
    expect(judge({ ...base, buildingUse: '제2종 근린생활시설' }).status).toBe('exclude');
    expect(judge({ ...base, violation: true }).loanOk).toBe(false);
    expect(judge({ ...base, area: 90 }).loanOk).toBe(false);
  });
  it('압류·신탁은 위험', () => {
    expect(judge({ ...base, seizure: true }).risk).toBe('danger');
    expect(judge({ ...base, trust: true }).risk).toBe('danger');
  });
  it('시세 모름, 소유자 3명 이상은 주의', () => {
    expect(judge({ ...base, salePrice: null }).status).toBe('caution');
    expect(judge({ ...base, owners: 3 }).status).toBe('caution');
  });
});
