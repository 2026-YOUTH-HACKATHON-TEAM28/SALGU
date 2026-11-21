import { expect, test, type Page } from '@playwright/test';

const isMobile = (page: Page) => (page.viewportSize()?.width ?? 1280) < 768;

async function startAsExample(page: Page) {
  await page.goto('/');
  await page.getByTestId('login-kakao').click();
  await expect(
    page.getByRole('heading', { name: '안녕하세요, 살구예요. 어떤 집을 찾고 있어요?' }),
  ).toBeVisible();
}

async function say(page: Page, text: string) {
  await page.getByTestId('composer-input').fill(text);
  await page.getByTestId('composer-send').click();
}

async function noHorizontalScroll(page: Page) {
  const over = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(over).toBeLessThanOrEqual(1);
}

test.describe('S-00 로그인', () => {
  test('예시 계정으로 들어가 계정 메뉴에서 로그아웃', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByRole('heading', { name: /살구/ })).toBeVisible();
    await page.getByTestId('login-kakao').click();
    await page.getByTestId('account-btn').click();
    const menu = page.getByTestId('account-menu');
    await expect(menu).toContainText('예시 계정(카카오 연결 전)');
    await page.getByTestId('logout').click();
    await expect(page.getByTestId('login-guest')).toBeVisible();
  });

  test('둘러보기로 들어가면 계정 메뉴에 카카오로 로그인', async ({ page }) => {
    await page.goto('/');
    await page.getByTestId('login-guest').click();
    await page.getByTestId('account-btn').click();
    await expect(page.getByTestId('account-menu')).toContainText('둘러보는 중');
    await expect(
      page.getByTestId('account-menu').getByRole('menuitem', { name: '카카오로 로그인' }),
    ).toBeVisible();
  });
});

test('조건에서 일정까지: 조건 카드, 그 자리 수정, 동네, 전화, 확인, 미팅, 일정', async ({ page }) => {
  await startAsExample(page);
  await noHorizontalScroll(page);

  // S-02 조건 카드: 말씀하신 조건, 중요한 항목 먼저
  await page.getByRole('button', { name: /여의도역으로 출근해요/ }).click();
  const cond = page.getByTestId('cond-card').last();
  await expect(cond.getByRole('heading', { name: '말씀하신 조건' })).toBeVisible();
  await expect(cond.getByTestId('cond-workplace')).toContainText('여의도역');
  await expect(cond.getByTestId('cond-rent')).toContainText('60만 원 이하');
  await expect(page.getByTestId('prefs')).toContainText('내 조건');

  // S-03 동네: 말하지 않은 출퇴근은 '살구가 정한 조건'
  await cond.getByTestId('cond-search').click();
  const dongs = page.getByTestId('dongs-card').last();
  await expect(dongs.getByTestId('dong-row')).toHaveCount(3);
  const latestCond = page.getByTestId('cond-card').last();
  await expect(latestCond.getByRole('heading', { name: '살구가 정한 조건' })).toBeVisible();
  await expect(latestCond.getByTestId('cond-maxCommute')).toContainText('살구가 채운 값');

  // 그 자리에서 월세 고치기
  await latestCond.getByTestId('edit-rent').click();
  const inline = latestCond.getByTestId('inline-rent');
  await inline.getByRole('textbox').or(inline.locator('input')).first().fill('70');
  await inline.getByRole('button', { name: '확인' }).click();
  await expect(page.getByTestId('cond-card').last().getByTestId('cond-rent')).toContainText('70만 원 이하');

  // S-04 전화 전 준비: 필수 칸 전에는 못 누름
  await page.getByTestId('dongs-call').last().click();
  const prep = page.getByTestId('callprep-card');
  const start = prep.getByTestId('start-calls');
  await expect(start).toBeDisabled();
  await prep.getByRole('button', { name: '12월 초' }).click();
  await prep.getByRole('button', { name: '2년' }).click();
  await prep.getByRole('button', { name: '이번 토요일 오후' }).click();
  await expect(start).toBeEnabled();
  await start.click();

  // S-05 AI 통화: 화면 정의서 문구
  const calls = page.getByTestId('calls-card');
  await expect(calls.getByTestId('call-row').first()).toBeVisible();
  await expect(calls.getByTestId('call-status').first()).toHaveText(
    /차례를 기다리는 중|신호 가는 중|통화 중|통화 내용 정리 중|방 있음|비슷한 방 없음|안 받음|AI 통화 거절|확인 못 함/,
  );

  // S-06 매물 확인: 통화가 끝나면 자동으로
  const checks = page.getByTestId('checks-card');
  await expect(checks).toBeVisible({ timeout: 60_000 });
  const listings = checks.getByTestId('listing');
  const count = await listings.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    const l = listings.nth(i);
    // 연락 상태는 머리 오른쪽, 확인 상태는 가격 줄 아래(같은 자리, 같은 문구)
    await expect(l.locator('.listing-head [data-testid="contact-status"]')).toHaveText(/답변 받음|답변 없음/);
    await expect(l.locator('.listing-check [data-testid="check-status"]')).toHaveText(
      /추천|주의|제외 권장|등기 대기/,
    );
  }

  // S-07 미팅: 주의 매물까지
  await checks.getByTestId('plan-caution').click();
  const plan = page.getByTestId('plan-card');
  const noPlan = page.getByText('추천이나 주의 매물이 없어서 미팅을 잡지 않았어요.');
  await expect(plan.or(noPlan)).toBeVisible();
  if (await noPlan.isVisible()) return;
  // 확정 전화가 끝나면 '연락 중'이 사라지고 방문 확정·시간 제안 받음·연락 못 함 중 하나
  await expect(plan.locator('[data-testid="contact-status"]', { hasText: '연락 중' })).toHaveCount(0, {
    timeout: 60_000,
  });
  const confirmed = await plan.locator('[data-testid="contact-status"]', { hasText: '방문 확정' }).count();

  // S-09 일정: 확정된 방문만
  if (isMobile(page)) await page.getByTestId('tab-sched').click();
  else await page.getByTestId('hdr-sched').click();
  const sched = page.getByTestId('schedule');
  await expect(sched).toBeVisible();
  await expect(sched.getByTestId('sched-item')).toHaveCount(confirmed);
  await noHorizontalScroll(page);
});

test('맞는 동네가 없으면 넓혀본 조건으로 표시하고 원래대로 되돌리기', async ({ page }) => {
  await startAsExample(page);
  await say(page, '강남역 출근, 월세 30만 원 이하, 출퇴근 20분 이내');
  await page.getByTestId('cond-card').last().getByTestId('cond-search').click();
  const nomatch = page.getByTestId('nomatch-card').last();
  await expect(nomatch).toBeVisible();
  await nomatch.getByTestId('widen-maxCommute').click();
  const cond = page.getByTestId('cond-card').last();
  await expect(cond.getByTestId('cond-maxCommute')).toContainText('넓혀본 값');
  await expect(cond.getByTestId('cond-maxCommute')).toContainText('원래 20분 이내');
  await cond.getByTestId('reset-maxCommute').click();
  await expect(page.getByTestId('cond-card').last().getByTestId('cond-maxCommute')).not.toContainText(
    '넓혀본 값',
  );
});

test('조건 골라서 찾기 양식: 회사를 안 고르면 안내', async ({ page }) => {
  await startAsExample(page);
  await page.getByTestId('open-cond-form').click();
  const form = page.getByTestId('cond-form').last();
  await form.getByTestId('cond-form-submit').click();
  await expect(form.getByRole('alert')).toHaveText('회사(학교) 위치를 골라 주세요.');
  await form.locator('select[name=workplace]').selectOption({ label: '강남역' });
  await form.locator('input[name=rent]').fill('65');
  await form.getByTestId('cond-form-submit').click();
  await expect(page.getByText('채운 조건으로 찾았어요.')).toBeVisible();
  await expect(page.getByTestId('dongs-card').or(page.getByTestId('nomatch-card')).last()).toBeVisible();
});

test('주민등록번호는 보내기 전에 가려요', async ({ page }) => {
  await startAsExample(page);
  await say(page, '990101-1234567 여의도 월세 50');
  await expect(page.getByTestId('toast')).toContainText('개인정보로 보이는 숫자는 가리고 보냈어요.');
  await expect(page.getByTestId('msg-user').last()).toContainText('990101-1******');
  await expect(page.getByTestId('chat-log')).not.toContainText('1234567');
});

test('지도와 일정 화면 전환', async ({ page }) => {
  await startAsExample(page);
  await page.getByRole('button', { name: /여의도역으로 출근해요/ }).click();
  await page.getByTestId('cond-card').last().getByTestId('cond-search').click();
  await expect(page.getByTestId('dongs-card')).toBeVisible();
  if (isMobile(page)) {
    await page.getByTestId('tab-map').click();
    await expect(page.getByTestId('bigmap')).toBeVisible();
    await expect(page.locator('#bigmap .leaflet-container, #bigmap.leaflet-container')).toHaveCount(1);
    await page.getByTestId('tab-sched').click();
    await expect(page.getByTestId('schedule')).toBeVisible();
    await page.getByTestId('tab-chat').click();
    await expect(page.getByTestId('chat-log')).toBeVisible();
  } else {
    await page.getByTestId('hdr-map').click();
    await expect(page.getByTestId('side')).toBeVisible();
    await expect(page.locator('#bigmap.leaflet-container')).toHaveCount(1);
    await page.getByTestId('dong-row').first().locator('.dong-main').click();
    await expect(page.getByTestId('map-sheet')).toBeVisible();
  }
  await noHorizontalScroll(page);
});
