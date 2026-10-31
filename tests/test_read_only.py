"""既定で書き込めないこと。読み取りは制限されないこと。"""

import pytest

from sheets_appender import ReadOnlyError

from conftest import make_meta


WRITES = {
    "append_many": lambda s: s.append_many({"2026-10": [{"ID": "1"}]}),
    "ensure_tabs": lambda s: s.ensure_tabs(["新しいタブ"]),
    "apply_layout": lambda s: s.apply_layout(["2026-10"]),
    "delete_tab": lambda s: s.delete_tab("2026-10"),
    "rename_tab": lambda s: s.rename_tab("2026-10", "2026-11"),
}


@pytest.mark.parametrize("name", sorted(WRITES))
def test_writes_are_blocked_by_default(spec, open_sheet, name):
    sheet, api = open_sheet(spec)
    with pytest.raises(ReadOnlyError, match="読み取り専用"):
        WRITES[name](sheet)
    # 止まる前にAPIを叩いていないこと（メタデータの取得だけは許す）
    assert not api.requests()
    assert not api.written()


def test_read_only_note_is_included(spec, open_sheet):
    sheet, _ = open_sheet(spec, read_only_note="移行中のため閉じています")
    with pytest.raises(ReadOnlyError, match="移行中のため閉じています"):
        sheet.append_many({"2026-10": [{"ID": "1"}]})


def test_writable_lets_writes_through(spec, open_sheet):
    sheet, api = open_sheet(spec, writable=True)
    sheet.apply_layout(["2026-10"])
    assert api.requests()


def test_reads_work_without_writable(spec, open_sheet):
    meta = make_meta(["2026-10", "集計"])
    sheet, api = open_sheet(spec, meta=meta)
    api.batch_get_result = {"valueRanges": [{"values": [["k1"], [""], ["k2"]]}]}

    assert sheet.tab_names() == ["2026-10", "集計"]
    assert sheet.data_tabs() == ["2026-10"]  # skip_tabs が効く
    assert sheet.existing_keys() == {"k1", "k2"}


def test_append_of_nothing_does_not_raise(spec, open_sheet):
    # 0件のときは関門より手前で返る。「追加なし」で落ちると使いづらい
    sheet, api = open_sheet(spec)
    assert sheet.append_many({}) == 0
    assert sheet.append_many({"2026-10": []}) == 0
    assert not api.calls


def test_ensure_tabs_of_existing_does_not_raise(spec, open_sheet):
    sheet, api = open_sheet(spec)
    sheet.ensure_tabs(["2026-10"])  # 既にある
    assert not api.requests()
