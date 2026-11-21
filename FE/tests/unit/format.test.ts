import { describe, expect, it } from 'vitest';
import { condValueText, depRent, maskPersonal, won } from '../../src/shared/format.js';
import { CHECK_LABEL, CONTACT_LABEL, callLabel } from '../../src/shared/labels.js';
import { WORKPLACES } from '../../src/server/mock/data.js';

describe('금액 표시', () => {
  it('만 원 단위', () => {
    expect(won(500)).toBe('500만 원');
    expect(won(10000)).toBe('1억 원');
    expect(won(12500)).toBe('1억 2,500만 원');
    expect(depRent(1000, 55)).toBe('1,000/55');
  });
});

describe('조건 문구', () => {
  it('회사 이름과 값', () => {
    expect(condValueText('workplace', 'yeouido', WORKPLACES)).toBe('여의도역');
    expect(condValueText('maxTransfer', 0, WORKPLACES)).toBe('환승 없이');
    expect(condValueText('builtAfter', null, WORKPLACES)).toBe('상관없음');
  });
});

describe('개인정보 가리기', () => {
  it('주민등록번호와 카드번호', () => {
    expect(maskPersonal('제 번호는 990101-1234567 이에요')).toBe('제 번호는 990101-1****** 이에요');
    expect(maskPersonal('1234 5678 9012 3456')).toBe('1234-****-****-3456');
    expect(maskPersonal('월세 55만 원')).toBe('월세 55만 원');
  });
});

describe('상태 문구', () => {
  it('연락 상태와 확인 상태는 서로 다른 문구', () => {
    const contact = Object.values(CONTACT_LABEL).map((l) => l.text);
    const check = Object.values(CHECK_LABEL).map((l) => l.text);
    expect(new Set(contact).size).toBe(contact.length);
    expect(new Set(check).size).toBe(check.length);
    expect(contact).toContain('연락 중');
    expect(contact).toContain('답변 없음');
    expect(contact).toContain('방문 확정');
  });
  it('통화 카드는 화면 정의서 S-05 문구', () => {
    expect(callLabel('waiting', null).text).toBe('차례를 기다리는 중');
    expect(callLabel('ringing', null).text).toBe('신호 가는 중');
    expect(callLabel('analyzing', null).text).toBe('통화 내용 정리 중');
    expect(callLabel('done', 'listing').text).toBe('방 있음');
    expect(callLabel('done', 'declined').text).toBe('AI 통화 거절');
  });
});
