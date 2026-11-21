from phone_agent.timing import response_gaps, turn_timing


def line(speaker, start, end, text="…"):
    return {"speaker": speaker, "start": start, "end": end, "text": text}


def test_turn_timing():
    transcript = [
        line("ai", 0.0, 4.0),
        line("broker", 4.5, 6.0),
        line("ai", 7.0, 9.0),        # 1.0초 뒤 응답
        line("broker", 8.5, 12.0),   # AI 말 끝나기 전에 중개사가 끼어듦
        line("ai", 14.5, 16.0),      # 2.5초 뒤
        line("ai", 16.2, 17.0),      # 이어 말함(응답 아님)
        line("broker", 17.5, 19.0),
        line("ai", 18.8, 20.0),      # 중개사 말이 끝나기 전에 AI가 말함
    ]
    timing = turn_timing(transcript)
    assert timing["response_gaps"] == [1.0, 2.5]
    assert timing["response_median"] == 1.75 and timing["response_p90"] == 2.5 and timing["response_max"] == 2.5
    assert timing["ai_turn_avg"] == 1.9 and timing["ai_turn_max"] == 4.0
    assert timing["ai_cut_ins"] == 1 and timing["broker_barge_ins"] == 1
    assert timing["call_seconds"] == 20.0
    assert response_gaps(transcript) == [None, None, 1.0, None, 2.5, None, None, -0.2]


def test_no_times_means_no_timing():
    assert turn_timing([{"speaker": "ai", "text": "안녕하세요"}]) is None
    assert turn_timing([]) is None
