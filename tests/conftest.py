"""Sheets API を丸ごと偽物に差し替える。テストは通信しない。"""

import pytest

import sheets_appender.client as client
from sheets_appender import Sheet, SheetSpec

SA_EMAIL = "sa@example.test"


class Request:
    """googleapiclient の「組み立てて execute する」形を真似る。"""

    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class Values:
    def __init__(self, api):
        self._api = api

    def batchGet(self, spreadsheetId=None, ranges=None):
        self._api.calls.append(("values.batchGet", list(ranges)))
        return Request(self._api.batch_get_result)

    def batchUpdate(self, spreadsheetId=None, body=None):
        self._api.calls.append(("values.batchUpdate", body))
        return Request({})

    def get(self, spreadsheetId=None, range=None):
        self._api.calls.append(("values.get", range))
        return Request(self._api.get_result)


class Api:
    def __init__(self, meta):
        self.calls = []
        self.meta = meta
        self.batch_get_result = {"valueRanges": []}
        self.get_result = {}
        self._values = Values(self)

    def values(self):
        return self._values

    def get(self, spreadsheetId=None):
        self.calls.append(("get", spreadsheetId))
        return Request(self.meta)

    def batchUpdate(self, spreadsheetId=None, body=None):
        self.calls.append(("batchUpdate", body))
        return Request({})

    # ── 取り出し用 ──────────────────────────────────────────────

    def requests(self):
        """batchUpdate に渡された requests を平らにして返す。"""
        out = []
        for name, body in self.calls:
            if name == "batchUpdate":
                out += body["requests"]
        return out

    def written(self):
        """values.batchUpdate に渡された data を平らにして返す。"""
        out = []
        for name, body in self.calls:
            if name == "values.batchUpdate":
                out += body["data"]
        return out


def make_meta(tabs, row_count=10, protected=0, conditional=0):
    return {
        "sheets": [
            {
                "properties": {
                    "title": title,
                    "sheetId": 100 + i,
                    "gridProperties": {"rowCount": row_count},
                },
                "protectedRanges": [
                    {"protectedRangeId": 900 + i * 10 + n} for n in range(protected)
                ],
                "conditionalFormats": [{"n": n} for n in range(conditional)],
            }
            for i, title in enumerate(tabs)
        ]
    }


@pytest.fixture
def spec():
    return SheetSpec(
        machine_columns=["ID", "名前", "登録日"],
        human_columns=["ステータス", "担当", "メモ"],
        hidden_columns=["ID"],
        column_widths={"名前": 240},
        dropdowns={"ステータス": ["未着手", "完了"]},
        initial_values={"ステータス": "未着手"},
        skip_tabs=frozenset({"集計"}),
    )


@pytest.fixture
def open_sheet(monkeypatch):
    """`Sheet` を偽物のAPIで開く。返り値は (sheet, api)。"""

    def _open(spec, meta=None, **kwargs):
        api = Api(meta if meta is not None else make_meta(["2026-10"]))

        class Credentials:
            service_account_email = SA_EMAIL

        class Service:
            def spreadsheets(self):
                return api

        monkeypatch.setattr(client, "load_credentials", lambda key_path=None: Credentials())
        monkeypatch.setattr(client, "build", lambda *a, **k: Service())
        monkeypatch.setattr(client.time, "sleep", lambda _: None)
        return Sheet(spec, "SPREADSHEET_ID", **kwargs), api

    return _open
