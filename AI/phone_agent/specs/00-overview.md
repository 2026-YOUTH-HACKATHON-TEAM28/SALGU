# 전화 에이전트 spec 세트: 개요

해커톤 당일 전화 에이전트를 **이 spec들에 맞춰** 만들거나 고치기 위한 문서입니다. 기능마다 spec 하나, spec마다 완료 조건과 커밋 하나입니다.

| 문서 | 내용 |
|---|---|
| [prompts.md](prompts.md) | 당일 Claude에게 붙여 넣을 프롬프트 |
| [interfaces.md](interfaces.md) | 모듈·클래스·함수 이름과 시그니처. 이대로 짜면 기존 테스트를 완료 조건으로 쓸 수 있음 |
| [assets/](assets/README.md) | **그대로 가져갈 자료**: pyproject, 예시 요청, 오류 문구, mock 대화록, LLM 추출 지시, 낱말 목록 |
| [lessons.md](lessons.md) | 지난 사흘의 실수 |
| [../contracts/io.md](../contracts/io.md), [api.md](api.md) | 입출력 형식(상세 / 요약) |

**기준**: 자료(문서·프롬프트·낱말·예시·mock 대화록)는 그대로 가져오고, 코드만 새로 짭니다.

## 무엇을 만드나

기획서 ④·⑤: 사용자가 승인한 중개사무소에 AI가 전화해 방·조건·보여 줄 수 있는 시간을 묻고(문의 통화), 사용자가 방과 시각을 고르면 다시 전화해 방문을 확정합니다(확정 통화).

```
BE/화면 ─POST 문의─▶ [접수·검사] ─▶ [한 통씩 거는 줄] ─▶ 공급사(한국AI통신) ─전화─▶ 중개사
                                         │ 끊기면
                                         ▼
                                   [전사 → LLM이 값 찾기 → 코드가 근거 줄 대조] ─▶ 결과
BE/화면 ─GET (1~2초)─▶ 결과 ─▶ 사용자가 방·시각 승인 ─POST 확정─▶ (같은 길로 확정 통화)
```

## 단계 (필수 S / 기본 M / 선택 L)

| 단계 | spec | 만드는 것 | 등급 | 시간 | 이 단계가 끝나면 |
|---|---|---|---|---|---|
| C1 | [01-skeleton](01-skeleton.md) | 요청 형식, mock 공급사, REST 4개, 기록, 한 통씩 순서대로 거는 줄 | S | 45분 | 키 없이 mock으로 문의 결과가 나옴 → **화면이 붙기 시작할 수 있음** |
| C2 | [02-policy](02-policy.md) | 발신 전 검사(하루 제한·영업시간·시간대), 재발신, demo 번호 고르기 | S | 30분 | 하루 제한·영업시간·재발신 동작 |
| C3 | [03-inquiry-call](03-inquiry-call.md) | 통화별 지시문, 고정 프롬프트, 공급사 연결 | S | 60분 | **시연 번호로 실제 문의 전화 한 통** |
| C4 | [04-extraction](04-extraction.md) | 전사 → 값 찾기 → 근거 줄 대조 → 결론 | S | 60분 | 실제 통화 결과가 형식대로 나옴 |
| C5 | [05-confirm-call](05-confirm-call.md) | 확정 묶음, 방문 상태, 확정 시각 안전장치 | M | 60분 | **문의 → 확정 두 번 통화 시연 가능** |
| C6 | [06-notify-registry](06-notify-registry.md) | 카카오·문자 알림, 등기부(문자·업로드) | L | 30분 | 확정 알림 한 통 |
| C7 | [07-mcp-dedupe](07-mcp-dedupe.md) | MCP 입구, 중복 매물 묶기 | L | 15분 | 챗봇이 도구로 부를 수 있음 |

시간이 모자라면 C5까지만 합니다. C1이 끝나는 대로 화면·BE 담당에게 mock 주소를 넘깁니다.

## 공통 약속

- 금액은 **만원** 정수, 시각은 **한국 시간** ISO 문자열(`2026-11-21T14:00:00+09:00`). 시간대 없는 시각은 한국 시간으로 봄
- 입출력 형식은 [contracts/io.md](../contracts/io.md)가 기준입니다. spec과 다르면 io.md를 따르고 spec을 고칩니다. 짧은 요약은 [api.md](api.md)
- ID는 서버가 만듭니다: 묶음 `bb_…`(문의)·`vb_…`(확정), 통화 `bc_…`
- 결론(방 있음, 확정 등)은 **코드가 정합니다.** LLM은 대화록에서 값과 줄 번호를 찾기만 합니다
- 비밀값(공급사 키, 시연 번호, 카카오 토큰, LLM 키)은 `.env`에만, 이름은 [.env.example](../.env.example)

## 모듈 지도

파일 이름은 [interfaces.md](interfaces.md)와 같습니다. 11-20 구현 기준이며, 코드를 새로 짤 때도 이 나눔을 따르면 단계별 커밋이 깔끔합니다.

| 파일 | spec |
|---|---|
| `schemas.py`, `app.py`, `service.py`(접수·기록·응답), `provider.py`(`MockProvider`) | C1 |
| `policy.py`, `service.py`(줄·재발신) | C2 |
| `instruction.py`, `provider.py`(`KatProvider`), `prompts/agent_prompt.md`, `trial.py` | C3 |
| `extract.py`, `timing.py` | C4 |
| `service.py`(확정), `policy.py`(`within_broker_slots`) | C5 |
| `notify.py`, `service.py`(등기부) | C6 |
| `mcp_server.py`, `dedupe.py` | C7 |

## 당일 작업 규칙 (리포 AGENTS.md)

- 수정은 `AI/`와 `data/kkiha/`만. FE·BE에 필요한 변경은 문서로 넘깁니다.
- 단계마다 완료 조건(테스트)을 통과하면 **그 단계 파일만** 커밋합니다. `git add .` 금지.
- 사용자가 입력한 프롬프트는 `data/kkiha/prompts/YYYY-MM-DD-주제.md`에 남깁니다.
