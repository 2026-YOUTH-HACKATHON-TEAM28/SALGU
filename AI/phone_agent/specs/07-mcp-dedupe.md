# C7. MCP 입구와 중복 매물 (선택)

## MCP (`mcp-phone`)

챗봇 LLM이 도구로 부를 수 있게, **REST와 같은 서비스**를 같은 서버의 `/mcp`(Streamable HTTP)에 얇게 엽니다. 규칙은 REST와 똑같이 적용됩니다.

| 도구 | REST |
|---|---|
| `call_brokers(approval_id, search, share, brokers, prep?, keep_transcript?)` | `POST /api/broker-call-batches` |
| `get_call_results(batch_id)` | 문의·확정 묶음 GET |
| `confirm_visits(approval_id, visits)` | `POST /api/visit-confirmations` |

- `mcp` 패키지가 없으면 REST만 엽니다(오류 아님).
- 기본으로 localhost로 온 요청만 받습니다. 배포해서 다른 주소로 부르려면 `PHONE_AGENT_MCP_HOST=0.0.0.0`.
- 결정(11-19): 챗봇이 공급사(한국AI통신) MCP를 직접 부르지 않고 이 입구를 거칩니다. 하루 제한·안전장치를 우회하지 못하게.

## 중복 매물 (`duplicate_groups`)

여러 사무소가 같은 방을 말했을 수 있습니다. 문의 묶음 결과에 후보를 묶어 줍니다.

- 서로 **다른 사무소**의 방끼리만 비교. 같은 사무소 안의 방은 묶지 않음
- **같은 건물 이름**(오피스텔·빌라 같은 일반 단어 제거 후)이어야 함. 층·호수는 둘 다 있을 때 다르면 묶지 않고, 한쪽이 모르면 막지 않음 → `suspected`
- 이유(`reasons`): "같은 건물: …", "같은 층: …", "같은 호수: …호", "보증금·월세 같음/다름"
- 확정 통화에서 받은 호수로 다시 계산: 모두 같은 호수로 확인되면 `likely_same`, 다르면 묶음에서 빠짐
- 최종 판정은 등기부 소재지(등기 담당)

## 완료 조건

- 테스트: `test_mcp.py`, `test_dedupe.py`, `test_service.py`의 `test_duplicate_groups_*`

## 커밋

`AI: 전화 에이전트 MCP 입구와 중복 매물 묶기`
