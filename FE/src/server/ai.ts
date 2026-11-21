/* OpenAI 연결. 집 찾기 흐름과 숫자는 계산 엔진이 맡고, AI는 두 가지만 해요.
 *  1) 규칙으로 못 뽑은 조건을 말에서 뽑기(JSON 형식으로만)
 *  2) 규칙으로 못 답한 질문에 답하기(살구 설명 문서를 근거로, 숫자 판정은 하지 않음)
 * 키가 없거나 실패하면 지금까지처럼 규칙으로만 답해요. 대화 내용과 키는 기록에 남기지 않아요. */
import type { CondKey, Workplace } from '../shared/types.js';

export interface AiConfig {
  apiKey: string;
  model: string;
  timeoutMs: number;
  /** 하루 전체 AI 호출 상한(비용 보호) */
  dailyCap: number;
}

const ANSWER_SYSTEM = [
  '너는 서울에서 혼자 살 집을 찾는 청년을 돕는 "살구"야. 한국어 해요체로 짧고 구체적으로 답해(3~5문장).',
  '줄표(—), 이모지, 화살표(→)는 쓰지 말고, 굵은 글씨나 마크다운 제목도 쓰지 마.',
  '시세, 월세, 점수, 위험 같은 숫자나 판정은 지어내지 마. 그런 숫자는 살구 계산 결과에만 있으니 "조건을 알려 주시면 계산해 드릴게요"처럼 안내해.',
  '참고 자료에 없는 제도·금액은 단정하지 말고 공식 공고를 확인하라고 해. 계약 판단은 공인중개사와 확인하라고 안내해.',
  '집 찾기와 관계없는 질문이면 한 문장으로 정중히 살구가 돕는 일을 알려 줘.',
].join(' ');

const EXTRACT_SYSTEM = [
  '사용자가 말한 집 찾기 조건만 JSON으로 뽑아. 말하지 않은 칸은 null 로 둬. 짐작하지 마.',
  '금액은 만 원 단위 정수. "1000/50"은 보증금 1000, 월세 50. "1억"은 10000.',
  'workplace 는 주어진 회사 목록의 id 중 하나만, 목록에 없으면 null.',
  'maxCommute 는 분, maxTransfer 는 횟수, builtAfter 는 연도.',
].join(' ');

/** 조건 뽑기 결과 모양(엄격한 JSON 스키마) */
function condSchema(workplaces: Workplace[]) {
  const nullable = (t: object) => ({ anyOf: [t, { type: 'null' }] });
  return {
    type: 'object',
    additionalProperties: false,
    required: [
      'workplace',
      'rent',
      'deposit',
      'maxCommute',
      'maxTransfer',
      'houseType',
      'builtAfter',
      'pet',
      'parking',
      'commercial',
    ],
    properties: {
      workplace: nullable({ type: 'string', enum: workplaces.map((w) => w.id) }),
      rent: nullable({ type: 'integer' }),
      deposit: nullable({ type: 'integer' }),
      maxCommute: nullable({ type: 'integer' }),
      maxTransfer: nullable({ type: 'integer' }),
      houseType: nullable({ type: 'string', enum: ['villa', 'officetel'] }),
      builtAfter: nullable({ type: 'integer' }),
      pet: nullable({ type: 'boolean' }),
      parking: nullable({ type: 'boolean' }),
      commercial: nullable({ type: 'string', enum: ['lively', 'quiet'] }),
    },
  };
}

interface ResponsesOutput {
  output?: { type: string; content?: { type: string; text?: string }[] }[];
  error?: { message?: string };
}

export class Ai {
  private used = { date: '', count: 0 };

  constructor(private readonly cfg: AiConfig) {}

  get enabled(): boolean {
    return Boolean(this.cfg.apiKey);
  }

  get model(): string {
    return this.cfg.model;
  }

  /** 하루 상한 안이면 1회 사용 처리 */
  private take(): boolean {
    const today = new Date().toISOString().slice(0, 10);
    if (this.used.date !== today) this.used = { date: today, count: 0 };
    if (this.used.count >= this.cfg.dailyCap) return false;
    this.used.count += 1;
    return true;
  }

  private async call(instructions: string, input: string, schema?: object): Promise<string | null> {
    if (!this.enabled || !this.take()) return null;
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), this.cfg.timeoutMs);
    try {
      const body: Record<string, unknown> = {
        model: this.cfg.model,
        instructions,
        input,
        max_output_tokens: 900,
        store: false,
      };
      if (/^(gpt-5|o\d)/.test(this.cfg.model)) body.reasoning = { effort: 'low' };
      if (schema) body.text = { format: { type: 'json_schema', name: 'conditions', schema, strict: true } };
      const res = await fetch('https://api.openai.com/v1/responses', {
        method: 'POST',
        headers: { Authorization: `Bearer ${this.cfg.apiKey}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      });
      const data = (await res.json().catch(() => ({}))) as ResponsesOutput;
      if (!res.ok) {
        // 키나 내용은 남기지 않고 상태만 남겨요.
        console.error(`[ai] OpenAI 응답 ${res.status}`);
        return null;
      }
      const text = (data.output ?? [])
        .flatMap((o) => o.content ?? [])
        .filter((c) => c.type === 'output_text')
        .map((c) => c.text ?? '')
        .join('')
        .trim();
      return text || null;
    } catch (err) {
      console.error(`[ai] OpenAI 호출 실패: ${(err as Error).name}`);
      return null;
    } finally {
      clearTimeout(timer);
    }
  }

  /** 말에서 조건 뽑기. 실패하면 빈 객체 */
  async extract(text: string, workplaces: Workplace[]): Promise<Partial<Record<CondKey, unknown>>> {
    const list = workplaces.map((w) => `${w.id}=${w.name}(${w.alias.join('/')})`).join(', ');
    const out = await this.call(`${EXTRACT_SYSTEM} 회사 목록: ${list}`, text, condSchema(workplaces));
    if (!out) return {};
    try {
      const raw = JSON.parse(out) as Record<string, unknown>;
      const values: Partial<Record<CondKey, unknown>> = {};
      for (const [k, v] of Object.entries(raw)) if (v !== null && v !== undefined) values[k as CondKey] = v;
      return values;
    } catch {
      return {};
    }
  }

  /** 규칙으로 못 답한 질문에 답하기 */
  async answer(question: string, context: string): Promise<string | null> {
    const out = await this.call(
      `${ANSWER_SYSTEM}\n\n아래 참고 자료와 사용자 상황을 근거로 답해.\n<참고자료>\n${context}\n</참고자료>`,
      question,
    );
    if (!out) return null;
    // 화면 규칙: 줄표·이모지·마크다운 굵게를 지워요.
    return out
      .replace(/[—–]/g, ',')
      .replace(/\*\*(.+?)\*\*/g, '$1')
      .replace(/^#+\s*/gm, '')
      .replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu, '')
      .trim();
  }
}
