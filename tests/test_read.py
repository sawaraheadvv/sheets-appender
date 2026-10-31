"""読み取り系。"""

import pytest
from googleapiclient.errors import HttpError

import sheets_appender.client as client
from sheets_appender import TabNotFoundError

from conftest import make_meta


def test_metadata_is_fetched_once(spec, open_sheet):
    # 毎回取るとタブ数に比例して読み取りが増え、毎分60回の上限に当たる
    sheet, api = open_sheet(spec)
    sheet.tab_names()
    sheet.tab_names()
    sheet.data_tabs()
    assert len([c for c in api.calls if c[0] == "get"]) == 1


def test_existing_keys_reads_column_a_of_every_data_tab(spec, open_sheet):
    sheet, api = open_sheet(spec, meta=make_meta(["2026-10", "2026-11", "集計"]))
    api.batch_get_result = {
        "valueRanges": [{"values": [["a"]]}, {"values": [["b"], ["  "]]}]
    }

    assert sheet.existing_keys() == {"a", "b"}
    ranges = [c[1] for c in api.calls if c[0] == "values.batchGet"][0]
    assert ranges == ["'2026-10'!A2:A", "'2026-11'!A2:A"]


def test_existing_keys_can_be_limited_to_given_tabs(spec, open_sheet):
    sheet, api = open_sheet(spec, meta=make_meta(["2026-10", "2026-11"]))
    api.batch_get_result = {"valueRanges": [{"values": [["a"]]}]}

    sheet.existing_keys(["2026-11"])

    ranges = [c[1] for c in api.calls if c[0] == "values.batchGet"][0]
    assert ranges == ["'2026-11'!A2:A"]


def test_existing_keys_of_no_tabs_is_empty(spec, open_sheet):
    sheet, api = open_sheet(spec, meta=make_meta(["集計"]))
    assert sheet.existing_keys() == set()
    assert not [c for c in api.calls if c[0] == "values.batchGet"]


def test_read_rows_pads_short_rows_and_drops_keyless_rows(spec, open_sheet):
    sheet, api = open_sheet(spec)
    api.batch_get_result = {
        "valueRanges": [
            {"values": [["1", "名前"], ["", "キーなし"], ["2"] + [""] * 8]}
        ]
    }

    rows = sheet.read_rows(["2026-10"])

    assert list(rows) == ["2026-10"]
    # 6列に揃う。キーの無い行は落ちる。長すぎる行は切られる
    assert rows["2026-10"] == [
        ["1", "名前", "", "", "", ""],
        ["2", "", "", "", "", ""],
    ]


def test_read_rows_of_nothing(spec, open_sheet):
    sheet, api = open_sheet(spec)
    assert sheet.read_rows([]) == {}
    assert not api.calls


def test_column_values(spec, open_sheet):
    sheet, api = open_sheet(spec)
    api.get_result = {"values": [["2026-10-01"], [""], ["2026-10-02"]]}

    assert sheet.column_values("2026-10", "登録日") == ["2026-10-01", "2026-10-02"]
    assert ("values.get", "'2026-10'!C2:C") in api.calls


def test_unknown_tab_raises(spec, open_sheet):
    sheet, _ = open_sheet(spec)
    with pytest.raises(TabNotFoundError, match="無いタブ"):
        sheet._tab_id("無いタブ")


def test_apply_layout_skips_tabs_that_do_not_exist(spec, open_sheet):
    sheet, api = open_sheet(spec, writable=True)
    sheet.apply_layout(["2026-10", "無いタブ"])
    protected = [r for r in api.requests() if "addProtectedRange" in r]
    assert len(protected) == 1


# ── execute のリトライ ──────────────────────────────────────────


class Resp:
    def __init__(self, status):
        self.status = status
        self.reason = "test"


class Flaky:
    """最初の n 回だけ失敗する request。"""

    def __init__(self, status, failures):
        self._status = status
        self._left = failures
        self.tries = 0

    def execute(self):
        self.tries += 1
        if self._left > 0:
            self._left -= 1
            raise HttpError(Resp(self._status), b"{}")
        return "ok"


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_transient_errors_are_retried(monkeypatch, status):
    monkeypatch.setattr(client.time, "sleep", lambda _: None)
    request = Flaky(status, failures=2)
    assert client.execute(request) == "ok"
    assert request.tries == 3


def test_other_errors_are_raised_immediately(monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda _: None)
    request = Flaky(403, failures=1)
    with pytest.raises(HttpError):
        client.execute(request)
    assert request.tries == 1


def test_retries_give_up_after_the_limit(monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda _: None)
    request = Flaky(429, failures=99)
    with pytest.raises(HttpError):
        client.execute(request, tries=3)
    assert request.tries == 3


# ── 鍵の読み込み ────────────────────────────────────────────────


def test_missing_credentials_explains_what_to_set(monkeypatch):
    monkeypatch.delenv(client.KEY_ENV, raising=False)
    monkeypatch.delenv(client.KEY_FILE_ENV, raising=False)
    with pytest.raises(client.SheetError, match=client.KEY_FILE_ENV):
        client.load_credentials()
