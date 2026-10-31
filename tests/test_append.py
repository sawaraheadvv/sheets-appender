"""追記が「どこに」「どの列を」書くか。"""

from conftest import make_meta


def rows_after(api):
    """values.batchUpdate に渡された最初の data を返す。"""
    return api.written()[0]


def test_appends_after_the_last_existing_row(spec, open_sheet):
    sheet, api = open_sheet(spec, writable=True)
    # 既に3行（ヘッダ＋2行）ある
    api.batch_get_result = {"valueRanges": [{"values": [["h"], ["r1"], ["r2"]]}]}

    written = sheet.append_many({"2026-10": [{"ID": "x"}]})

    assert written == 1
    assert rows_after(api)["range"] == "'2026-10'!A4"


def test_appends_to_row_1_when_the_tab_is_empty(spec, open_sheet):
    sheet, api = open_sheet(spec, writable=True)
    api.batch_get_result = {"valueRanges": [{}]}

    sheet.append_many({"2026-10": [{"ID": "x"}]})

    assert rows_after(api)["range"] == "'2026-10'!A1"


def test_writes_only_up_to_the_initial_value_column(spec, open_sheet):
    sheet, api = open_sheet(spec, writable=True)
    api.batch_get_result = {"valueRanges": [{"values": [["h"]]}]}

    sheet.append_many(
        {"2026-10": [{"ID": "1", "名前": "テスト", "登録日": "2026-10-31"}]}
    )

    # 「担当」「メモ」は含まれない。空文字でも書いたら人の入力を消す
    assert rows_after(api)["values"] == [["1", "テスト", "2026-10-31", "未着手"]]


def test_initial_value_can_be_overridden_per_row(spec, open_sheet):
    sheet, api = open_sheet(spec, writable=True)
    api.batch_get_result = {"valueRanges": [{"values": [["h"]]}]}

    sheet.append_many({"2026-10": [{"ID": "1", "ステータス": "完了"}]})

    assert rows_after(api)["values"] == [["1", "", "", "完了"]]


def test_missing_machine_columns_become_empty(spec, open_sheet):
    sheet, api = open_sheet(spec, writable=True)
    api.batch_get_result = {"valueRanges": [{"values": [["h"]]}]}

    sheet.append_many({"2026-10": [{"ID": "1"}]})

    assert rows_after(api)["values"] == [["1", "", "", "未着手"]]


def test_reads_every_column_before_choosing_the_row(spec, open_sheet):
    # 人が右側の列だけに書いた行を潰さないため、A:F まで読む
    sheet, api = open_sheet(spec, writable=True)
    api.batch_get_result = {"valueRanges": [{"values": [["h"]]}]}

    sheet.append_many({"2026-10": [{"ID": "1"}]})

    ranges = [c[1] for c in api.calls if c[0] == "values.batchGet"][0]
    assert ranges == ["'2026-10'!A:F"]


def test_grid_is_grown_when_rows_do_not_fit(spec, open_sheet):
    sheet, api = open_sheet(spec, meta=make_meta(["2026-10"], row_count=3), writable=True)
    api.batch_get_result = {"valueRanges": [{"values": [["h"], ["r1"], ["r2"]]}]}

    sheet.append_many({"2026-10": [{"ID": str(i)} for i in range(5)]})

    grow = [r for r in api.requests() if "appendDimension" in r]
    assert len(grow) == 1
    # 4行目から5行 = 8行必要。いまは3行なので5行足す
    assert grow[0]["appendDimension"]["length"] == 5
    assert grow[0]["appendDimension"]["dimension"] == "ROWS"


def test_grid_is_not_grown_when_rows_fit(spec, open_sheet):
    sheet, api = open_sheet(spec, meta=make_meta(["2026-10"], row_count=100), writable=True)
    api.batch_get_result = {"valueRanges": [{"values": [["h"]]}]}

    sheet.append_many({"2026-10": [{"ID": "1"}]})

    assert not [r for r in api.requests() if "appendDimension" in r]


def test_empty_tabs_are_dropped(spec, open_sheet):
    sheet, api = open_sheet(spec, meta=make_meta(["2026-10", "2026-11"]), writable=True)
    api.batch_get_result = {"valueRanges": [{"values": [["h"]]}]}

    written = sheet.append_many({"2026-10": [{"ID": "1"}], "2026-11": []})

    assert written == 1
    ranges = [c[1] for c in api.calls if c[0] == "values.batchGet"][0]
    assert ranges == ["'2026-10'!A:F"]


def test_ensure_tabs_writes_the_header_for_new_tabs_only(spec, open_sheet):
    sheet, api = open_sheet(spec, meta=make_meta(["2026-10"]), writable=True)

    sheet.ensure_tabs(["2026-10", "2026-11"])

    added = [r for r in api.requests() if "addSheet" in r]
    assert [r["addSheet"]["properties"]["title"] for r in added] == ["2026-11"]
    assert api.written() == [{"range": "'2026-11'!A1", "values": [spec.header]}]
