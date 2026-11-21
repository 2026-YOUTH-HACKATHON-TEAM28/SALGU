from phone_agent.timing import response_gaps, turn_timing


def line(speaker, start, end, text="가나다"):
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
    assert timing["ai_talk_seconds"] == 9.5
    assert response_gaps(transcript) == [None, None, 1.0, None, 2.5, None, None, -0.2]


def test_speaking_rate_per_speaker():
    from phone_agent.timing import syllables_per_sec
    transcript = [
        line("ai", 0.0, 2.0, "안녕하세요 살구입니다"),        # 10음절 / 2초 = 5.0
        line("broker", 2.5, 3.0, "네"),                        # 1초 미만은 뺌
        line("broker", 3.5, 5.5, "하나 있긴 한데요 삼층이에요"),  # 12음절 / 2초 = 6.0
        line("ai", 6.0, 8.0, "관리비는 얼마인가요?"),          # 9음절 / 2초 = 4.5
    ]
    assert syllables_per_sec(transcript, "ai") == 4.75  # 5.0과 4.5의 중앙값
    assert syllables_per_sec(transcript, "broker") == 6.0
    timing = turn_timing(transcript)
    assert timing["ai_syllables_per_sec"] == 4.75 and timing["broker_syllables_per_sec"] == 6.0


def test_no_times_means_no_timing():
    assert turn_timing([{"speaker": "ai", "text": "안녕하세요"}]) is None
    assert turn_timing([]) is None
