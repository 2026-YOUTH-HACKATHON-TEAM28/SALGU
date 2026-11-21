from phone_agent.dedupe import building_key, duplicate_groups


def item(call_id, broker, building, floor=None, unit=None, deposit=None, rent=None, index=0, confirmed_unit=None):
    data = {"call_id": call_id, "listing_index": index, "broker": broker,
            "listing": {"building": building, "floor": floor, "unit": unit,
                        "deposit_manwon": deposit, "monthly_rent_manwon": rent}}
    if confirmed_unit:
        data["confirmed_unit"] = confirmed_unit
    return data


def test_building_key_drops_generic_words():
    assert building_key("해든빌라") == building_key("해든 빌라") == building_key("해든") == "해든"
    assert building_key("해든 오피스텔") == "해든"
    assert building_key(None) == ""


def test_same_building_from_different_brokers_is_suspected():
    groups = duplicate_groups([
        item("bc_1", "한빛공인중개사", "해든빌라", "3층", deposit=1000, rent=60),
        item("bc_2", "새봄공인중개사", "해든빌라", "3층", deposit=1000, rent=60),
    ])
    assert groups == [{
        "group_id": "dup1", "status": "suspected",
        "members": [{"call_id": "bc_1", "listing_index": 0, "broker": "한빛공인중개사"},
                    {"call_id": "bc_2", "listing_index": 0, "broker": "새봄공인중개사"}],
        "reasons": ["같은 건물: 해든빌라", "같은 층: 3층", "보증금·월세 같음"],
    }]


def test_rules_that_keep_rooms_apart():
    # 같은 사무소 안의 방은 묶지 않음
    assert duplicate_groups([item("bc_1", "한빛", "해든빌라", index=0), item("bc_1", "한빛", "해든빌라", index=1)]) == []
    # 건물이 다름
    assert duplicate_groups([item("bc_1", "한빛", "해든빌라"), item("bc_2", "새봄", "새솔빌")]) == []
    # 층이 둘 다 있고 다름
    assert duplicate_groups([item("bc_1", "한빛", "해든빌라", "3층"), item("bc_2", "새봄", "해든빌라", "2층")]) == []
    # 호수가 둘 다 있고 다름
    assert duplicate_groups([item("bc_1", "한빛", "해든빌라", unit="301호"), item("bc_2", "새봄", "해든빌라", unit="302호")]) == []
    # 건물 이름이 없으면 비교하지 않음
    assert duplicate_groups([item("bc_1", "한빛", None), item("bc_2", "새봄", None)]) == []


def test_unknown_floor_does_not_block_and_price_difference_is_a_reason():
    groups = duplicate_groups([item("bc_1", "한빛", "해든빌라", "3층", deposit=1000, rent=60),
                               item("bc_2", "새봄", "해든 빌라", None, deposit=1000, rent=65)])
    assert groups[0]["status"] == "suspected"
    assert groups[0]["reasons"] == ["같은 건물: 해든빌라", "보증금·월세 다름"]


def test_confirmed_units_decide_likely_same_or_split():
    same = duplicate_groups([item("bc_1", "한빛", "해든빌라", "3층", confirmed_unit="302호"),
                             item("bc_2", "새봄", "해든빌라", "3층", confirmed_unit="302호")])
    assert same[0]["status"] == "likely_same" and "같은 호수: 302호" in same[0]["reasons"]
    split = duplicate_groups([item("bc_1", "한빛", "해든빌라", "3층", confirmed_unit="302호"),
                              item("bc_2", "새봄", "해든빌라", "3층", confirmed_unit="303호")])
    assert split == []
    half = duplicate_groups([item("bc_1", "한빛", "해든빌라", "3층", confirmed_unit="302호"),
                             item("bc_2", "새봄", "해든빌라", "3층")])
    assert half[0]["status"] == "suspected"


def test_three_brokers_one_group_and_numbering():
    groups = duplicate_groups([
        item("bc_1", "한빛", "해든빌라", "3층"), item("bc_2", "새봄", "해든빌라", "3층"), item("bc_3", "푸른", "해든빌라"),
        item("bc_1", "한빛", "새솔빌", "2층", index=1), item("bc_3", "푸른", "새솔빌", "2층", index=1),
    ])
    assert [g["group_id"] for g in groups] == ["dup1", "dup2"]
    assert [len(g["members"]) for g in groups] == [3, 2]
