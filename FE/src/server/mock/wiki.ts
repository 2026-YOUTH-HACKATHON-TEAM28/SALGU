/* 개념 설명(mock). 실서비스에서는 AI가 이 문서를 근거로 답해요. */
import { STANDARD } from './data.js';

export interface Concept {
  title: string;
  body: string[];
}

export const CONCEPTS: Record<string, Concept> = {
  환산월세: {
    title: '환산월세',
    body: [
      '보증금과 월세가 서로 다른 방을 한 숫자로 비교하려고 보증금을 월세로 바꿔 더한 값이에요.',
      `계산: 월세 + 보증금 × 전월세전환율(${STANDARD.convRate}%) ÷ 12`,
      '예를 들어 보증금 1,000만 원, 월세 50만 원이면 50 + 1,000 × 0.05 ÷ 12 = 약 54만 원이에요.',
    ],
  },
  전월세전환율: {
    title: '전월세전환율',
    body: [
      '보증금을 월세로 바꿀 때 쓰는 비율이에요. 법정 상한은 한국은행 기준금리에 2%p를 더한 값이에요.',
      `지금 살구가 쓰는 값은 기준금리 ${STANDARD.baseRate}% + ${STANDARD.spread}%p = ${STANDARD.convRate}%예요.`,
    ],
  },
  전환율: {
    title: '전월세전환율',
    body: [
      '보증금을 월세로 바꿀 때 쓰는 비율이에요. 법정 상한은 한국은행 기준금리에 2%p를 더한 값이에요.',
      `지금 살구가 쓰는 값은 ${STANDARD.convRate}%예요.`,
    ],
  },

  확정일자: {
    title: '전입신고와 확정일자',
    body: [
      '이사한 날 바로 전입신고를 하고 계약서에 확정일자를 받아야 보증금을 지킬 권리(대항력, 우선변제권)가 생겨요.',
      '전입신고는 이사 후 14일 안에 해야 하고, 정부24나 주민센터에서 함께 할 수 있어요.',
    ],
  },
  전입신고: {
    title: '전입신고',
    body: [
      '이사 후 14일 안에 정부24나 주민센터에서 해요. 확정일자도 같이 받아 두면 좋아요.',
      '전입신고 다음 날 0시부터 대항력이 생겨요.',
    ],
  },
  청년지원: {
    title: '청년 주거 지원',
    body: [
      '서울시 청년월세지원은 월 최대 20만 원을 최대 12개월 받을 수 있어요(공고 기준, 소득·재산 조건 있음).',
      '조건과 신청 기간은 해마다 바뀌어서, 신청 전에 청년몽땅정보통 공고를 꼭 확인해 주세요.',
    ],
  },
};

export function conceptOf(topic: string): Concept | null {
  if (/청년/.test(topic)) return CONCEPTS['청년지원'] ?? null;
  return CONCEPTS[topic] ?? null;
}
