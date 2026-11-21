"""대화 한 턴: 말 이해(intake) → 최소 조건이 모이면 BE에 검색 요청 → 들은 결과를 전하고 답한다.

말풍선 순서 (messages)
1. reply            "좋아요! 신촌 근처, 보증금 1000만·월세 50만 이하 집으로 찾아볼게요."
2. backend_request  "살구 검색 서버에 조건을 보내 집을 요청했습니다."
3. backend_response "아, 조건에 맞는 집이 3곳 있다고 합니다."
4. answer           "그중 추천 1순위는 … 예요. …"
숫자는 BE 응답 값을 그대로 쓴다(챗봇은 계산하지 않음).
"""

from . import backend, intake

_TYPES = {"officetel": "오피스텔", "villa": "빌라"}


def heard(res):
    """BE에게 들은 내용을 전하는 말."""
    if not res["ok"]:
        return "아, 검색 서버에서 답이 오지 않았다고 합니다."
    if res["count"] == 0:
        return "아, 지금 조건에 맞는 집은 없다고 합니다."
    return f"아, 조건에 맞는 집이 {res['count']}곳 있다고 합니다."


def answer(res):
    """들은 결과를 보고 사용자에게 하는 답."""
    if not res["ok"]:
        return "잠시 후 다시 시도해 주세요. 말씀하신 조건은 그대로 기억해 둘게요."
    if res["count"] == 0 or not res["candidates"]:
        return "예산을 조금 올리거나 지역을 넓혀 볼까요? 예: '월세 60까지 괜찮아', '마포 쪽도 봐 줘'"
    top = res["candidates"][0]
    rent = top.get("monthly_rent_manwon")
    money = f"보증금 {top.get('deposit_manwon')}만" + (f"·월세 {rent}만" if rent else " 전세")
    details = [_TYPES.get(top.get("housing_type"), top.get("housing_type") or "집"), money]
    if top.get("area_m2"):
        details.append(f"전용 {top['area_m2']:g}㎡")
    if top.get("floor") is not None:
        details.append(f"{top['floor']}층")
    if top.get("station") and top.get("walk_to_station_min") is not None:
        details.append(f"{top['station']}까지 걸어서 {top['walk_to_station_min']}분")
    name = str(top.get("name"))
    last = name[-1:]
    has_jong = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 > 0
    text = f"그중 추천 1순위는 '{name}'{'이에요' if has_jong else '예요'}. ({', '.join(details)})"
    return text + " 다른 곳도 볼까요, 아니면 조건을 바꿔 볼까요?"


def turn(message, prev_card=None, session_id=None):
    """→ intake 결과 + {"messages", "backend"}. reply는 말풍선을 이어 붙인 글."""
    r = intake.intake(message, prev_card)
    messages = [{"kind": "reply", "text": r["reply"]}]
    res = None
    card = r["card"]
    if r["intent"] == "search" and card and card.get("ready") and r["changed"]:
        res = backend.search(card, session_id)
        req = "살구 검색 서버에 조건을 보내 집을 요청했습니다."
        if res["mock"]:
            req += " (로컬 시험이라 예시 응답을 씁니다)"
        messages += [{"kind": "backend_request", "text": req},
                     {"kind": "backend_response", "text": heard(res)},
                     {"kind": "answer", "text": answer(res)}]
    r["messages"] = messages
    r["backend"] = res
    r["reply"] = "\n".join(m["text"] for m in messages)
    return r
