/* 말에서 조건과 의도를 뽑는 규칙(mock). 실서비스에서는 AI 대화 에이전트가 같은 모양으로 돌려줘요. */
import type { CondKey, Workplace } from '../../shared/types.js';

export interface Extracted {
  values: Partial<Record<CondKey, unknown>>;
  /** 데이터로 확인할 수 없는 조건(조용함, 채광 등) */
  unknowns: string[];
  /** 뜻이 둘인 말 */
  ambiguous: 'clean' | null;
}

const WORD_NUM: Record<string, number> = { 천: 1000, 오백: 500, 삼천: 3000, 이천: 2000, 오천: 5000 };

/** "1000", "천만", "1억", "1억 5000", "500만" -> 만 원 */
export function parseMoney(raw: string): number | null {
  const s = raw.replace(/[,\s]/g, '');
  const eok = /(\d+(?:\.\d+)?)억(\d+)?/.exec(s);
  if (eok) return Math.round(Number(eok[1]) * 10000 + (eok[2] ? Number(eok[2]) : 0));
  const num = /(\d+)/.exec(s);
  if (num) return Number(num[1]);
  for (const [w, n] of Object.entries(WORD_NUM)) if (s.startsWith(w)) return n;
  return null;
}

export function findWorkplace(text: string, workplaces: Workplace[]): Workplace | null {
  const t = text.replace(/\s/g, '');
  for (const w of workplaces) {
    if (t.includes(w.name.replace(/\s/g, ''))) return w;
  }
  for (const w of workplaces) {
    if (w.alias.some((a) => t.toLowerCase().includes(a.toLowerCase()))) return w;
  }
  return null;
}

export function extractConds(text: string, workplaces: Workplace[]): Extracted {
  const t = text.replace(/\s+/g, ' ');
  const values: Partial<Record<CondKey, unknown>> = {};
  const unknowns: string[] = [];

  const wp = findWorkplace(t, workplaces);
  if (wp) values.workplace = wp.id;

  const dep =
    /보증금\s*(?:은|는|이|을)?\s*((?:\d+(?:\.\d+)?\s*억\s*\d*)|\d[\d,]*|천|오백|이천|삼천|오천)/.exec(t);
  if (dep?.[1]) {
    const m = parseMoney(dep[1]);
    if (m !== null) values.deposit = m;
  }

  const rent =
    /월세\s*(?:는|은|가|를)?\s*(\d{2,3})/.exec(t) ??
    /(\d{2,3})\s*만\s*원?\s*(?:이하|까지|정도|안쪽|내외|선)/.exec(t.replace(/보증금\s*\S+/g, ''));
  if (rent?.[1]) values.rent = Number(rent[1]);

  const commute =
    /(?:출퇴근|통근|출근)[^\d]{0,8}(\d{2})\s*분/.exec(t) ??
    /(\d{2})\s*분\s*(?:이내|안쪽|안으로|이하|까지)/.exec(t);
  if (commute?.[1] && !/배차/.test(t.slice(Math.max(0, (commute.index ?? 0) - 4), commute.index))) {
    values.maxCommute = Number(commute[1]);
  }

  if (/환승\s*(?:없이|안\s*하|0)/.test(t)) values.maxTransfer = 0;
  else {
    const x = /환승\s*(\d)\s*(?:번|회)/.exec(t);
    if (x?.[1]) values.maxTransfer = Number(x[1]);
  }

  const bus = /배차\s*(?:간격)?\s*(\d{1,2})\s*분/.exec(t);
  if (bus?.[1]) values.maxBusInterval = Number(bus[1]);

  if (/오피스텔/.test(t)) values.houseType = 'officetel';
  else if (/원룸|빌라|다세대/.test(t)) values.houseType = 'villa';

  const year = /(20\d{2}|19\d{2})\s*년\s*(?:이후|부터|넘)/.exec(t);
  if (year?.[1]) values.builtAfter = Number(year[1]);
  else if (/신축|새\s*집|새로\s*지은/.test(t) && !/중요/.test(t)) values.builtAfter = 2018;
  else if (/준공\S*\s*상관\s*없|오래\S*\s*괜찮|연식\S*\s*상관\s*없/.test(t)) values.builtAfter = null;

  if (/(?:출퇴근|통근)\S*\s*(?:이|가)?\s*(?:제일|가장|젤)\s*중요/.test(t)) values.priority = 'commute';
  else if (/(?:가격|월세|싼\s*게|돈)\S*\s*(?:이|가)?\s*(?:제일|가장|젤)\s*중요/.test(t))
    values.priority = 'price';
  else if (/(?:새\s*집|신축)\S*\s*(?:이|가)?\s*(?:제일|가장|젤)\s*중요/.test(t)) values.priority = 'new';

  if (/번화|상권|맛집|먹자/.test(t)) values.commercial = 'lively';
  else if (/주택가/.test(t)) values.commercial = 'quiet';

  if (/고양이|강아지|반려|애완/.test(t)) values.pet = !/안\s*키|없어요|없음/.test(t);
  if (/주차/.test(t)) values.parking = !/필요\s*없|안\s*해도/.test(t);

  if (/싼\s*편|저렴한\s*편|하위/.test(t)) values.priceBand = 'low';

  if (/조용/.test(t)) unknowns.push('조용함');
  if (/채광|햇빛|해\s*잘\s*드/.test(t)) unknowns.push('채광');
  if (/전망|뷰/.test(t)) unknowns.push('전망');

  const ambiguous = /깨끗한|깔끔한/.test(t) && values.builtAfter === undefined ? 'clean' : null;
  return { values, unknowns, ambiguous };
}

export type Intent =
  | { kind: 'moreDongs' }
  | { kind: 'cheaper' }
  | { kind: 'shorter' }
  | { kind: 'newer' }
  | { kind: 'detail'; no: number }
  | { kind: 'callOnly'; nos: number[] }
  | { kind: 'callAll' }
  | { kind: 'editConds' }
  | { kind: 'condForm' }
  | { kind: 'search' }
  | { kind: 'plan'; includeCaution: boolean }
  | { kind: 'final' }
  | { kind: 'oneByOne' }
  | { kind: 'greeting' }
  | { kind: 'concept'; topic: string }
  | { kind: 'other' };

export function intentOf(text: string): Intent {
  const t = text.replace(/\s+/g, ' ').trim();
  if (/^(안녕|하이|hi|hello)/i.test(t)) return { kind: 'greeting' };
  if (/조건\s*골라서\s*찾/.test(t)) return { kind: 'condForm' };
  if (/하나씩\s*물어/.test(t)) return { kind: 'oneByOne' };
  if (/다른\s*동네/.test(t)) return { kind: 'moreDongs' };
  if (/더\s*싼|더\s*저렴/.test(t)) return { kind: 'cheaper' };
  if (/(?:통근|출퇴근)\s*더\s*짧|더\s*가까운/.test(t)) return { kind: 'shorter' };
  if (/더\s*새\s*집|더\s*신축/.test(t)) return { kind: 'newer' };
  const detail = /(\d)\s*번\s*(?:동네)?\s*(?:자세히|더\s*알려|설명)/.exec(t);
  if (detail?.[1]) return { kind: 'detail', no: Number(detail[1]) };
  if (/(?:다|모두|전부)\s*전화/.test(t)) return { kind: 'callAll' };
  const only = /(\d)\s*번(?:\s*(?:이랑|하고|,|와|과)\s*(\d)\s*번)?\s*(?:만)?\s*전화/.exec(t);
  if (only?.[1]) return { kind: 'callOnly', nos: [Number(only[1]), ...(only[2] ? [Number(only[2])] : [])] };
  if (/주의\s*매물까지/.test(t)) return { kind: 'plan', includeCaution: true };
  if (/(?:추천\s*매물로|미팅\s*잡아|방문\s*잡아|약속\s*잡아)/.test(t))
    return { kind: 'plan', includeCaution: false };
  if (/최종\s*추천/.test(t)) return { kind: 'final' };
  if (/조건\s*(?:바꿀|바꾸|고칠|고치|수정)/.test(t)) return { kind: 'editConds' };
  if (/^(?:이대로\s*)?찾아\s*줘?$|^찾기$/.test(t)) return { kind: 'search' };
  const concept =
    /(환산월세|전월세\s*전환율|전환율|근저당|전세\s*대출|확정일자|전입신고|청년\s*(?:월세)?\s*지원|등기부)/.exec(
      t,
    );
  if (concept?.[1] && /(뭐|무엇|알려|설명|어떻게|받을\s*수|언제|\?)/.test(t)) {
    return { kind: 'concept', topic: concept[1].replace(/\s/g, '') };
  }
  return { kind: 'other' };
}
