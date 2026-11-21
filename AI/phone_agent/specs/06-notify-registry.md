# C6. 알림과 등기부 (선택)

## 알림

| 언제 (`kind`) | 문구 예 |
|---|---|
| 문의 묶음이 모두 끝남(`inquiry_done`, 한 번) | "[살구] 봉천동 중개사무소 2곳 문의가 끝났어요. 방 있음 1곳 · 없음 1곳 · 확인 못 함 0곳." |
| 확정 통화가 끝남(`visit`) | 확정된 방만 "방문 확정 11/21(토) 오후 2시 …", 제안받은 방은 "아직 확정 아님" |
| 등기부 문자가 들어옴(`registry`) | "[살구] 한빛공인중개사에서 등기부를 보냈어요." |

- 보내는 길: ① 카카오톡 '나에게 보내기'(`POST https://kapi.kakao.com/v2/api/talk/memo/default/send`, 텍스트 200자, 토큰 만료면 refresh 한 번) → 실패하면 ② 문자(demo, `PHONE_AGENT_NOTIFY_TO` 또는 첫 시연 번호, 공급사 `POST /messages`) → mock·설정 없음이면 ③ 기록만
- 묶음 결과의 `notifications[]`에 `{id, at, kind, batch_id, call_id, text, channel(kakao/sms/log), status(sent/logged/failed), error}`
- **확정 알림은 `confirmed`일 때만.** 요청 중·승인 필요는 확정으로 쓰지 않음(기획서)

## 등기부

| 경로 | 동작 |
|---|---|
| 중개사 문자·MMS | 살구 070 번호(`KAT_FROM_NUMBER`)로 받음. 30초마다 공급사 수신함(`GET /messages?status=received`)을 읽어, 보낸 번호로 최근 7일 안에 건 통화에 연결(시연은 "보내 주겠다"고 했고 아직 안 받은 가장 최근 통화 먼저). 본문 주민번호는 바로 가림. 첨부는 저장하지 않고 요청 때 공급사에서 받아 넘김 |
| 사용자 업로드 | `POST /api/broker-calls/{call_id}/registry-docs?listing_index=` 본문에 PDF(10MB). 메모리에만, 사실 정리 뒤 `DELETE /api/registry-docs/{id}` 또는 24시간 뒤 삭제 |

둘 다 그 문의 통화의 `registry_docs[]`에 `{message_id, received_at, type, text, source(sms/upload), listing_index, media[]}`로 들어옵니다. 사실 정리(소유자·근저당 등)는 등기 담당 몫입니다.

## 완료 조건

- 테스트: `test_notify.py`, `test_service.py`의 `test_inquiry_summary_notified_once`, `test_demo_notifies_by_sms_to_the_one_number`, `test_registry_message_attached_to_call`, `test_upload*`, `test_uploaded_*`
- 실제: 카카오 토큰으로 확정 알림 한 통이 내 카카오톡에 옴

## 커밋

`AI: 전화 에이전트 알림(카카오·문자)과 등기부 수신·업로드`

## 함정

- 카카오·문자 실제 발송과 등기부 MMS 실제 수신은 11-20까지 확인하지 못했음. 시연 전에 한 번 보내 볼 것
