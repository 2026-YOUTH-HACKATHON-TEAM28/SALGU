# 카카오톡 알림 (나에게 보내기) — 시연 연결

> 상태: **시연용 0.1**. 실서비스에서는 BE가 카카오 로그인에 `talk_message`를 붙이고 토큰을 `users`에 암호화해 저장한 뒤 보낸다.

사용자가 살구에서 카카오로 로그인하고 "카카오톡 메시지 전송"에 동의하면, 살구 알림이 그 사람 카톡의 **나와의 채팅**으로 간다. 받는 사람은 동의한 본인뿐이다.

```
사용자 ─ https://sample.localhostbar.com/notify/login ─▶ Caddy ─▶ 챗봇(127.0.0.1:8095)
        ◀─ 카카오 동의 화면 (talk_message) ─────────────────────────┘
카카오 ─ https://sample.localhostbar.com/notify/callback?code=… ─▶ Caddy ─▶ 챗봇: 토큰 저장 + 시험 메시지
서버 안 ─ POST http://127.0.0.1:8095/notify/send {"text": "..."} ─▶ 동의한 사람 모두에게 발송
```

## 1. 카카오 디벨로퍼스 (살구 앱) — 한 번만

| 메뉴 | 넣을 값 |
|---|---|
| 앱 → 플랫폼 → Web → 사이트 도메인 | `https://sample.localhostbar.com`, `http://localhost:8090` |
| 카카오 로그인 → 리다이렉트 URI | `https://sample.localhostbar.com/notify/callback`, `http://localhost:8090/notify/callback` |
| 카카오 로그인 → 동의항목 → 카카오톡 메시지 전송(talk_message) | 이용 중 동의 (설정 완료) |
| 비즈 앱 전환 | 완료 |

Client Secret을 "사용함"으로 켰다면 서버 `~/salgu-chat/agent.env`에 `KAKAO_CLIENT_SECRET=`이 있어야 한다. 배포 스크립트는 `GEMINI_*`, `SALGU_DB_*`, `KAKAO_REST_API_KEY`만 옮기므로 서버에서 직접 넣는다.

## 2. 서버 (FE 배포 담당) — 한 번만

Caddy 설정의 `sample.localhostbar.com` 블록에서, 화면 서버로 넘기기 **전에** 아래 두 줄을 넣는다. 이 두 주소만 챗봇으로 간다.

```
sample.localhostbar.com {
    handle /notify/login    { reverse_proxy 127.0.0.1:8095 }
    handle /notify/callback { reverse_proxy 127.0.0.1:8095 }
    handle                  { reverse_proxy 127.0.0.1:8080 }   # 기존 화면 서버
}
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
PARTS=chat bash deploy/deploy-stack.sh     # FE 폴더에서: 최신 챗봇 배포
```

- `/notify/send`, `/notify/subscribers`, 관리 화면은 **바깥에 열지 않는다.** 프록시 헤더가 붙은 요청은 403이다.
- 동의한 사람 정보는 `~/salgu-chat/data/notify/subscribers.json`(배포해도 유지)에 있다. refresh token이 들어 있으므로 권한 600 폴더에 둔다.

## 3. 쓰는 법

- 사용자: `https://sample.localhostbar.com/notify/login` → 로그인·동의 → 카톡에 "카톡 알림이 연결됐어요"가 온다.
- 보내기(서버 안에서):
  ```bash
  curl -s -X POST http://127.0.0.1:8095/notify/send -H 'Content-Type: application/json' \
       -d '{"text":"[살구] 이화부동산 통화 결과: 방 있음, 토요일 오후 방문 가능해요."}'
  ```
  한 사람만: `"kakao_id": "123"` 추가. 버튼 링크: `"link": "https://sample.localhostbar.com/..."` (없으면 그 사람이 연결한 사이트).
- 문구는 200자까지(넘으면 자름).

## 자주 나는 오류

| 오류 | 고칠 곳 |
|---|---|
| KOE006 | 리다이렉트 URI 등록이 빠짐 |
| KOE010 / invalid_client | Client Secret 필요 → `agent.env`에 `KAKAO_CLIENT_SECRET` |
| invalid_scope, KOE205 | 동의항목 talk_message 설정 확인 |
| -402 | 사용자가 메시지 전송에 동의하지 않음 → 다시 `/notify/login` |
| -401, invalid_grant | 토큰 만료·연결 끊김 → 다시 `/notify/login` |
