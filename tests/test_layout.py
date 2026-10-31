"""書式のリクエストの組み立て。APIは呼ばない。"""

from sheets_appender import Palette, SheetSpec, layout

from conftest import SA_EMAIL, make_meta


def build(spec, protected=0, conditional=0):
    meta = make_meta(["2026-10"], protected=protected, conditional=conditional)
    return layout.requests_for(spec, meta["sheets"][0], SA_EMAIL)


def only(requests, key):
    return [r[key] for r in requests if key in r]


def test_machine_columns_are_protected_for_the_service_account_only(spec):
    protected = only(build(spec), "addProtectedRange")
    assert len(protected) == 1
    rng = protected[0]["protectedRange"]
    assert rng["range"]["startColumnIndex"] == 0
    assert rng["range"]["endColumnIndex"] == 3  # 機械の列だけ
    # editors を省略すると「編集者全員」が既定になり保護が無効になる
    assert rng["editors"] == {"users": [SA_EMAIL]}
    assert rng["requestingUserCanEdit"] is False


def test_protection_note_is_used(spec):
    spec = SheetSpec(
        machine_columns=spec.machine_columns,
        human_columns=spec.human_columns,
        protection_note="触らないで",
    )
    protected = only(build(spec), "addProtectedRange")
    assert protected[0]["protectedRange"]["description"] == "触らないで"


def test_existing_protections_are_removed_first(spec):
    requests = build(spec, protected=2)
    assert len(only(requests, "deleteProtectedRange")) == 2
    # 消してから張る
    assert list(requests[0]) == ["deleteProtectedRange"]


def test_conditional_formats_are_left_alone_without_extra_layout(spec):
    requests = build(spec, conditional=3)
    assert not only(requests, "deleteConditionalFormatRule")


def test_conditional_formats_are_rebuilt_with_extra_layout(spec):
    spec = SheetSpec(
        machine_columns=spec.machine_columns,
        human_columns=spec.human_columns,
        extra_layout=lambda s, tab_id: [{"addConditionalFormatRule": {"x": tab_id}}],
    )
    requests = build(spec, conditional=3)
    deletes = only(requests, "deleteConditionalFormatRule")
    # 後ろから消す（index が詰まるため）
    assert [d["index"] for d in deletes] == [2, 1, 0]
    assert only(requests, "addConditionalFormatRule") == [{"x": 100}]


def test_hidden_columns(spec):
    hidden = [
        r["updateDimensionProperties"]
        for r in build(spec)
        if r.get("updateDimensionProperties", {}).get("properties", {}).get("hiddenByUser")
    ]
    assert len(hidden) == 1
    assert hidden[0]["range"]["startIndex"] == 0  # ID列


def test_header_row_is_frozen(spec):
    props = only(build(spec), "updateSheetProperties")
    assert props[0]["properties"]["gridProperties"]["frozenRowCount"] == 1


def test_filter_covers_every_column(spec):
    # 表示列だけに張ると、並べ替えでキー列と人の入力が置き去りになる
    rng = only(build(spec), "setBasicFilter")[0]["filter"]["range"]
    assert rng["startColumnIndex"] == 0
    assert rng["endColumnIndex"] == len(spec.header)


def test_dropdown_clears_the_human_range_then_sets_one_column(spec):
    validations = only(build(spec), "setDataValidation")
    assert len(validations) == 2
    # 1つめは規則の消去（rule を持たない）。人の列の範囲全体
    assert "rule" not in validations[0]
    assert validations[0]["range"]["startColumnIndex"] == 3
    assert validations[0]["range"]["endColumnIndex"] == 6
    # 2つめがステータス列のプルダウン
    assert validations[1]["range"]["startColumnIndex"] == 3
    assert validations[1]["range"]["endColumnIndex"] == 4
    values = validations[1]["rule"]["condition"]["values"]
    assert [v["userEnteredValue"] for v in values] == ["未着手", "完了"]
    # strict にしない。選択肢を増やす前に人が手で入れた値で作業を止めないため
    assert validations[1]["rule"]["strict"] is False


def test_no_validation_requests_without_dropdowns(spec):
    spec = SheetSpec(
        machine_columns=spec.machine_columns, human_columns=spec.human_columns
    )
    assert not only(build(spec), "setDataValidation")


def test_column_widths(spec):
    widths = [
        r["updateDimensionProperties"]
        for r in build(spec)
        if "pixelSize" in r.get("updateDimensionProperties", {}).get("properties", {})
    ]
    assert len(widths) == 1
    assert widths[0]["properties"]["pixelSize"] == 240
    assert widths[0]["range"]["startIndex"] == 1  # 名前列


def test_palette_is_applied(spec):
    red = {"red": 1.0, "green": 0.0, "blue": 0.0}
    spec = SheetSpec(
        machine_columns=spec.machine_columns,
        human_columns=spec.human_columns,
        palette=Palette(machine_header_bg=red),
    )
    cells = only(build(spec), "repeatCell")
    header = cells[0]["cell"]["userEnteredFormat"]
    assert header["backgroundColor"] == red
    assert header["textFormat"]["bold"] is True


def test_body_rows_have_no_end_so_appended_rows_are_covered(spec):
    # append は直上行の書式を継ぎ、clear は書式を消さない。
    # 末尾まで塗らないとヘッダの色が全行に伝播する
    body = [
        r["repeatCell"]
        for r in build(spec)
        if r.get("repeatCell", {}).get("range", {}).get("startRowIndex") == 1
    ]
    assert body
    for r in body:
        assert "endRowIndex" not in r["range"]
        assert r["cell"]["userEnteredFormat"]["textFormat"]["bold"] is False


def test_sheet_without_human_columns_skips_the_human_ranges():
    spec = SheetSpec(machine_columns=["ID", "名前"])
    cells = only(build(spec), "repeatCell")
    # ヘッダと本文がそれぞれ機械の分だけ
    assert len(cells) == 2
    for r in cells:
        assert r["range"]["endColumnIndex"] == 2
