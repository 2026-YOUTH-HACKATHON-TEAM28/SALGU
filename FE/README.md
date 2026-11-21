# 살구 화면 (FE)

서울에서 혼자 살 집을 찾는 청년을 위한 채팅 서비스 '살구'의 화면이에요. 회사 위치와 예산을 말하면 출퇴근하기 괜찮은 동네를 고르고, 그 동네 중개사무소에 AI가 전화해 비슷한 방을 묻고, 등기부와 건축물대장으로 위험을 확인한 뒤 집 보러 갈 약속까지 잡아요.

- 화면 버전: v1 (`src/shared/version.ts`)
- 기준 문서: 화면 정의서 S-00~S-12
- 요청 기록: [PROMPTS.md](./PROMPTS.md)
- BE 전달 문서: [docs/BACKEND_HANDOFF.md](./docs/BACKEND_HANDOFF.md) (API, JSON 모양, 테이블 제안, 실제 응답 예시)

## 구성

| 영역 | 기술 | 하는 일 |
|---|---|---|
| 화면 | TypeScript(strict), lit-html, Vite | 채팅, 카드, 지도, 일정. 빌드하면 파일 이름에 해시가 붙어 캐시 문제가 없어요 |
| 서버 | Node 22+, Fastify | 빌드한 화면과 `/api` 를 함께 내보내요(nginx 없음) |
| mock API | `src/server/mock` | 실제 BE와 같은 `/api` 경로로 응답해요. 조건 뽑기, 동네 찾기, 전화·등기·확정 통화 시뮬레이션 |
| 지도 | 카카오맵, 안 되면 OpenStreetMap(Leaflet) | 동네·매물·동선 |
| 시험 | Vitest, Playwright | 계산·규칙·API 단위 시험, PC 1280px·모바일 390px 화면 동작 시험 |

숫자(환산월세, 순위 점수, 시세 판정, 위험 비율)는 계산 엔진(`src/server/mock/engine.ts`)이 내요. 답변 아래에 출처를 실데이터 / 예시 값 / 시뮬레이션 / 기준값으로 표시해요. 지금 시세, 통근, 중개사무소, 등기 숫자는 모두 예시 값과 시뮬레이션이에요.

## 폴더

| 경로 | 내용 |
|---|---|
| `index.html`, `src/client/main.ts` | 화면 시작점 |
| `src/client/store.ts`, `api.ts` | 화면 상태, 서버 호출(통화 중에는 2.5초마다 확인, 실패하면 간격을 늘려요) |
| `src/client/components/` | 로그인, 헤더, 대화, 내 조건, 조건 양식, 일정 탭 |
| `src/client/components/cards/` | 조건, 동네, 전화 준비, AI 통화, 매물 확인, 미팅 계획, 최종 추천 카드 |
| `src/client/map/` | 지도 엔진(카카오맵·OpenStreetMap)과 큰 지도 |
| `src/shared/` | 화면과 서버가 함께 쓰는 타입, 상태 문구(한 곳에서만 정의), 표시 형식 |
| `src/server/` | 서버(`app.ts`), 라우트, 저장소(파일), 설정 |
| `src/server/mock/` | mock 데이터, 계산 엔진, 대화 규칙, 통화 시뮬레이션 |
| `tests/unit`, `tests/e2e` | 단위 시험, 화면 동작 시험 |
| `deploy/` | 배포 스크립트, systemd 서비스, 서버 환경 파일 예시 |

## 화면 문구 규칙

- 매물 카드의 연락 상태(연락 전, 연락 중, 답변 없음, 답변 받음, 시간 제안 받음, 방문 확정, 연락 못 함)는 카드 머리 오른쪽, 확인 상태(확인 전, 등기 대기, 추천, 주의, 제외 권장)는 가격 줄 바로 아래에 둬요. 문구는 `src/shared/labels.ts` 에서만 정해요.
- AI 통화 카드 문구는 화면 정의서 S-05 방식(차례를 기다리는 중, 신호 가는 중, 통화 중, 통화 내용 정리 중, 방 있음 등)이에요.
- 조건 카드는 회사·출퇴근·월세·보증금을 먼저 보이고, '말씀하신 조건'과 '살구가 정한 조건(채운 값·넓혀본 값)'을 나눠요. 월세·보증금·출퇴근은 그 자리에서 고쳐요.
- 줄표, 이모지는 쓰지 않아요. 상태는 색 점과 글자로 보여요.

## 로컬 실행

```bash
npm install
npm run dev            # 화면 http://localhost:5173 (API 는 8787, vite 가 /api 를 넘겨줘요)
```

운영과 같은 모양으로 보려면:

```bash
npm run build
PORT=8080 npm start    # http://localhost:8080
```

Windows 에서 npm 설정(`script-shell`)이 `/bin/bash` 로 되어 있으면 `npm run` 이 실패해요. 그때는 `node_modules/.bin/` 의 명령을 직접 쓰거나 `npm run --script-shell=cmd.exe <이름>` 으로 실행해 주세요.

환경 변수는 [.env.example](./.env.example) 를 보세요. `MOCK_TIME_SCALE` 을 키우면 mock 통화가 빨리 끝나요.

## 시험

```bash
npm run check          # 타입, 린트, 포맷, 단위 시험
npm run test:e2e       # 빌드 후 화면 동작 시험(설치된 Chrome 사용, Edge 는 PW_CHANNEL=msedge)
```

## 배포

```bash
bash deploy/deploy.sh                 # 서버 주소는 FE/.deploy-host(Git 제외) 또는 DEPLOY_HOST
STOP_OLD=1 bash deploy/deploy.sh      # 옛 zipsa 서비스가 8080을 쓰고 있으면 멈추고 배포
```

- 서버에 `~/salgu-fe/releases/<시각>` 으로 올리고 `current` 링크를 바꾼 뒤 systemd `salgu-fe` 를 다시 띄워요. 최근 5개만 남겨요.
- 설정은 서버 `~/salgu-fe/salgu-fe.env`(권한 600)에만 있어요. 처음 배포 때 예시로 만들어지고, 카카오맵 키(`KAKAO_MAP_KEY`)는 서버에서 직접 넣어요.
- 앞단 Caddy 가 `sample.localhostbar.com` 을 8080으로 넘겨요. `TRUST_PROXY` 에 적은 주소에서 온 요청만 https·방문자 IP 정보를 믿어요.

## 운영 보호

- 세션 쿠키 `sg_sid`: HttpOnly, SameSite=Lax, https 에서는 Secure. 30일 동안 안 쓰면 지워요.
- 다른 사이트에서 보낸 쓰기 요청은 막고(Origin 확인, JSON 본문만), 요청 수를 제한해요(전체 1분 300번, 말 30번).
- 보안 헤더(CSP 등), 본문 64KB 제한, 입력값 검사, 주민등록번호·카드번호 가림(보내기 전과 저장 전 모두).
- 대화는 계정별로 나뉘고 다른 사람의 대화는 열 수 없어요. 문의 통화는 계정마다 하루 10통까지예요.

## 아직 mock 인 것

| 기능 | 지금 | 실제로 바꿀 때 |
|---|---|---|
| 로그인 | 예시 계정, 둘러보기 | 카카오 로그인(`/oauth2/authorization/kakao`) |
| 대화·조건 뽑기 | 규칙 | BE와 AI 대화 에이전트 |
| 실거래·통근·버스·중개사무소 | 결정적 난수 예시 값 | BE 수집 배치 |
| 문의·확정 통화 | 시뮬레이션(전화 에이전트 v0.3.1 결과 모양) | 전화 에이전트 |
| 등기·건축물대장 | 가상 문서 | 등기 수신, 건축HUB |
| 카카오톡 알림 | 시험 연결(보내지 않음), 화면 알림 | 카카오톡 나에게 보내기 |
