# 세션 캐시 (Session Cache) 형식

> 상태: **초안 0.1**. 추천 계산 메서드(BE·AI)와 합의하기 전입니다.

챗봇은 대화(세션)마다 지금까지의 대화 상태를 **캐시 JSON 파일 하나**로 들고 있습니다. 추천 계산 메서드는 이 캐시에서 키워드를 뽑아 추천 매물을 만듭니다. 챗봇은 계산하지 않습니다.

## 어디에 있나

- 파일: `AI/chat_agent/.cache/sessions/{session_id}.json` (Git에 올리지 않는 캐시)
- 폴더는 `.env`의 `SESSION_CACHE_DIR`로 바꿀 수 있습니다.
- 사용자가 말할 때마다 같은 파일을 덮어씁니다. 마지막 대화 후 `SESSION_TTL_HOURS`(기본 24)시간이 지나면 만료되어 지웁니다.

## 읽는 법

```python
import sys; sys.path.insert(0, "AI/chat_agent/src")
from salgu_chat import session_cache

kw = session_cache.keywords("3cfac8cabda2")   # 추천 계산에 쓸 키워드. 세션이 없으면 None
cache = session_cache.load("3cfac8cabda2")    # 캐시 전체
if cache and cache["ready"]:
    ...  # 최소 조건(지역·보증금·월세)이 다 모였을 때만 추천
```

HTTP로도 읽을 수 있습니다: `GET /api/sessions/{session_id}/keywords`, `GET /api/sessions/{session_id}`

## 예시

```json
{
  "version": "0.1",
  "session_id": "3cfac8cabda2",
  "created_at": "2026-11-21T11:03:11+09:00",
  "updated_at": "2026-11-21T11:04:02+09:00",
  "expires_at": "2026-11-22T11:04:02+09:00",
  "ready": true,
  "missing": [],
  "keywords": {
    "avoid_areas": ["홍대"],
    "deposit_manwon": 1000,
    "housing_types": ["officetel"],
    "monthly_rent_manwon": 50,
    "preferred_areas": ["신촌"]
  },
  "card": { "version": "0.2-draft", "conditions": { "...": "조건 카드 전체 (condition_card.md)" } },
  "last_search": {
    "at": "2026-11-21T11:03:40+09:00", "mock": true, "ok": true, "count": 3, "error": null,
    "candidates": [ { "name": "...", "deposit_manwon": 1000, "monthly_rent_manwon": 48 } ]
  },
  "turn_count": 3,
  "history": [
    {
      "turn": 1, "at": "2026-11-21T11:03:11+09:00",
      "user": "신촌에 원하는 매물좀 찾아줘",
      "intent": "search", "via": "rules", "guard": null,
      "changed": ["preferred_areas"], "fixes": [],
      "messages": [ { "kind": "reply", "text": "좋아요! 신촌 근처 집으로 알아둘게요. 보증금이랑 월세는 어느 정도 생각하세요?" } ],
      "searched": false
    }
  ]
}
```

## 필드

| 필드 | 설명 |
|---|---|
| `ready` | 최소 조건(지역·보증금·월세, 전세면 월세 없음)이 다 모였는지. `true`일 때 추천합니다. |
| `missing` | 아직 모르는 최소 조건: `area`, `deposit`, `monthly_rent` |
| `keywords` | **추천 계산용 키워드.** 조건 카드의 각 칸을 `{칸: 값}`으로 편 것. 회사 위치(`workplace`)는 이름. 칸 이름과 값의 뜻은 `condition_card.md`와 같습니다. |
| `card` | 조건 카드 전체. 근거(`evidence`), 직접 말함/추론(`source`)이 필요할 때 봅니다. |
| `pending_action` | 사용자가 "이 집 보고 싶어"라고 해서 만든 전화 요청 초안(승인 전). BE가 승인 화면을 만들 때 읽습니다. 형식: `call_request.md` |
| `last_search` | 마지막 검색 요청과 받은 결과. `mock: true`면 로컬 예시 응답(실제 매물 아님). |
| `history` | 턴별 기록. `user`는 개인정보를 가린 사용자 말, `messages`는 챗봇이 한 말풍선들(`reply`, `backend_request`, `backend_response`, `answer`), `changed`는 그 턴에 바뀐 칸 |

## 합의할 점

- 추천 계산 메서드가 캐시 파일을 직접 읽을지, HTTP(`/api/sessions/{id}/keywords`)로 읽을지, 검색 요청 본문의 `keywords`를 쓸지
- 여러 서버에서 돌 때는 파일 대신 Redis 같은 공용 캐시로 옮길지
