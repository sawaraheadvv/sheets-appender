"""Google スプレッドシートの読み書き。

認証はサービスアカウント。対象のスプレッドシートに、SAのメールアドレスを
編集者として共有しておく必要がある。

守るべき原則は2つだけ:
  1. 人が書く列には絶対に触らない
  2. 行を削除・移動・並べ替えしない。追記と、機械の列の更新だけ

**既定では書き込めない。** `Sheet(spec, id, writable=True)` で明示的に開く。
うっかり他人の作業中のシートを書き換えないようにするため。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Set

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from . import layout
from .spec import SheetSpec

# Sheets API だけ。drive スコープは要求しない（共有されたシート以外に触れない）
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

KEY_ENV = "GOOGLE_SERVICE_ACCOUNT_KEY"
KEY_FILE_ENV = "GOOGLE_SERVICE_ACCOUNT_KEY_FILE"


class SheetError(Exception):
    """スプレッドシートの操作に失敗した"""


class ReadOnlyError(SheetError):
    """読み取り専用で開いたシートに書き込もうとした"""


class TabNotFoundError(SheetError):
    """指定したタブが存在しない"""


def load_credentials(key_path: Optional[Path] = None):
    """サービスアカウント鍵を読む。

    CI では鍵の中身を Secrets に入れるため環境変数から、手元ではファイルから
    読む。どちらでも同じコードが動くようにする。

    環境変数ファイル（dotenv）は読まない。必要なら利用側で読み込むこと。
    """
    raw = os.environ.get(KEY_ENV)
    if raw:
        return service_account.Credentials.from_service_account_info(
            json.loads(raw), scopes=SCOPES
        )

    path = key_path or os.environ.get(KEY_FILE_ENV)
    if not path:
        raise SheetError(
            "サービスアカウント鍵が指定されていません。\n"
            f"  環境変数 {KEY_ENV}（JSONの中身）か\n"
            f"  {KEY_FILE_ENV}（ファイルパス）を設定するか、\n"
            "  key_path 引数で渡してください。"
        )
    return service_account.Credentials.from_service_account_file(
        str(path), scopes=SCOPES
    )


def execute(request, tries: int = 6):
    """429（レート超過）と一時的なサーバエラーを指数バックオフで待つ。

    Sheets API の上限はユーザーあたり毎分60リクエスト。タブが増えると
    簡単に当たるため、呼び出し回数を減らすだけでなく再試行も要る。
    """
    for attempt in range(tries):
        try:
            return request.execute()
        except HttpError as e:
            transient = e.resp.status in (429, 500, 502, 503, 504)
            if not transient or attempt == tries - 1:
                raise
            wait = min(60, 5 * 2**attempt)
            print(f"    APIが混雑（{e.resp.status}）。{wait}秒待って再試行します")
            time.sleep(wait)


class Sheet:
    """1つのスプレッドシートを、`spec` の形の表として扱う。

    Args:
        spec: 列構成と見た目（→ `SheetSpec`）
        spreadsheet_id: スプレッドシートのID（URLの `/d/` と `/edit` の間）
        key_path: サービスアカウント鍵のパス。省略時は環境変数
        writable: True で書き込みを許可する。**既定は読み取り専用**
        read_only_note: 読み取り専用のまま書こうとしたときに、エラーの末尾に
            足す一文。「なぜ閉じているか」を利用側が説明するために使う
    """

    def __init__(
        self,
        spec: SheetSpec,
        spreadsheet_id: str,
        key_path: Optional[Path] = None,
        *,
        writable: bool = False,
        read_only_note: str = "",
    ):
        self.spec = spec
        self.spreadsheet_id = spreadsheet_id
        self.writable = writable
        self.read_only_note = read_only_note
        credentials = load_credentials(key_path)
        self.service_account_email = credentials.service_account_email
        self._api = build(
            "sheets", "v4", credentials=credentials, cache_discovery=False
        ).spreadsheets()
        self._meta_cache: Optional[dict] = None

    # ── 書き込みの関門 ──────────────────────────────────────────

    def _require_write(self, what: str) -> None:
        if self.writable:
            return
        message = (
            f"読み取り専用で開かれています（{what}）。\n"
            "  書き込むには Sheet(..., writable=True) を指定してください。"
        )
        if self.read_only_note:
            message += f"\n  {self.read_only_note}"
        raise ReadOnlyError(message)

    # ── 読み取り ────────────────────────────────────────────────

    def _meta(self) -> dict:
        """スプレッドシートのメタデータ。タブ構成が変わるまで使い回す。

        これを毎回取りに行くとタブ数に比例して読み取りが増え、毎分60回の
        上限に当たる（実測で12タブ目前に429になった）。
        """
        if self._meta_cache is None:
            self._meta_cache = execute(
                self._api.get(spreadsheetId=self.spreadsheet_id)
            )
        return self._meta_cache

    def _invalidate(self) -> None:
        self._meta_cache = None

    def tab_names(self) -> List[str]:
        return [s["properties"]["title"] for s in self._meta()["sheets"]]

    def data_tabs(self) -> List[str]:
        """データが入っているタブだけを返す（`spec.skip_tabs` を除く）。"""
        return [t for t in self.tab_names() if t not in self.spec.skip_tabs]

    def _tab(self, tab: str) -> dict:
        for s in self._meta()["sheets"]:
            if s["properties"]["title"] == tab:
                return s
        raise TabNotFoundError(f"タブが見つかりません: {tab}")

    def _tab_id(self, tab: str) -> int:
        return self._tab(tab)["properties"]["sheetId"]

    def _row_count(self, tab: str) -> int:
        return self._tab(tab)["properties"]["gridProperties"]["rowCount"]

    def existing_keys(self, tabs: Optional[List[str]] = None) -> Set[str]:
        """A列のキーを集める。既定は全データタブ。

        **1タブでも読み漏らすと、その分だけ重複して出力される。**

        `tabs` を渡すとそのタブだけを見る。同じ行を別の切り口でもう一枚
        出したいときに使う。存在しないタブを渡すと batchGet が失敗するので、
        呼び出し側で絞ること。
        """
        tabs = self.data_tabs() if tabs is None else tabs
        if not tabs:
            return set()

        # タブごとに get すると毎分60回の上限に当たる。batchGet で1回にまとめる
        result = execute(
            self._api.values().batchGet(
                spreadsheetId=self.spreadsheet_id,
                # A列 = キー。ヘッダ行を飛ばす
                ranges=[f"'{t}'!A2:A" for t in tabs],
            )
        )
        keys: Set[str] = set()
        for value_range in result.get("valueRanges", []):
            for row in value_range.get("values", []):
                if row and row[0].strip():
                    keys.add(row[0].strip())
        return keys

    def column_values(self, tab: str, name: str) -> List[str]:
        """1タブの1列を読む。空セルは落とす。"""
        column = chr(ord("A") + self.spec.index(name))
        result = execute(
            self._api.values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{tab}'!{column}2:{column}",
            )
        )
        return [r[0] for r in result.get("values", []) if r and r[0].strip()]

    def read_rows(self, tabs: List[str]) -> Dict[str, List[List[str]]]:
        """タブごとの全データ行を返す。バックアップなどに使う。

        行は `spec.header` の長さに揃える（右端が空の行は短く返ってくるため）。
        A列が空の行は捨てる（グリッドを広げただけの空行）。
        """
        if not tabs:
            return {}

        # タブごとに get すると毎分60回の上限に当たる。batchGet で1回にまとめる
        header = self.spec.header
        result = execute(
            self._api.values().batchGet(
                spreadsheetId=self.spreadsheet_id,
                ranges=[f"'{t}'!A2:{self.spec.last_column}" for t in tabs],
            )
        )
        out: Dict[str, List[List[str]]] = {}
        for tab, value_range in zip(tabs, result.get("valueRanges", [])):
            rows = []
            for row in value_range.get("values", []):
                if not row or not row[0].strip():
                    continue
                padded = row + [""] * (len(header) - len(row))
                rows.append(padded[: len(header)])
            out[tab] = rows
        return out

    # ── 書き込み ────────────────────────────────────────────────
    #
    # Sheets API の上限は毎分60リクエスト（読み・書きそれぞれ）。
    # タブ単位でループしながら都度APIを叩くと、12タブで簡単に超える。
    # そのため「全タブ分をまとめて1リクエストにする」のを原則にする。

    def rename_tab(self, old: str, new: str) -> None:
        self._require_write(f"タブ名の変更 {old} → {new}")
        execute(
            self._api.batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    "requests": [
                        {
                            "updateSheetProperties": {
                                "properties": {
                                    "sheetId": self._tab_id(old),
                                    "title": new,
                                },
                                "fields": "title",
                            }
                        }
                    ]
                },
            )
        )
        self._invalidate()

    def delete_tab(self, tab: str) -> None:
        self._require_write(f"タブの削除 {tab}")
        execute(
            self._api.batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"requests": [{"deleteSheet": {"sheetId": self._tab_id(tab)}}]},
            )
        )
        self._invalidate()

    def ensure_tabs(self, tabs: List[str]) -> None:
        """無いタブをまとめて作り、ヘッダ行を書く。

        **既存タブのヘッダは書き換えない。** 人が列を足しているかもしれず、
        上書きするとその列が消えるため。
        """
        missing = [t for t in tabs if t not in self.tab_names()]
        if not missing:
            return
        self._require_write(f"タブの作成 {missing}")

        execute(
            self._api.batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    "requests": [
                        {"addSheet": {"properties": {"title": t}}} for t in missing
                    ]
                },
            )
        )
        self._invalidate()

        execute(
            self._api.values().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={
                    "valueInputOption": "RAW",
                    "data": [
                        {"range": f"'{t}'!A1", "values": [self.spec.header]}
                        for t in missing
                    ],
                },
            )
        )

    def append_many(self, rows_by_tab: Dict[str, List[dict]]) -> int:
        """タブごとの行をまとめて追記する。既存行には一切触らない。

        書き込むのは `spec.written_columns` だけ。そこから右は空のまま残す。
        空文字を書き込むと、後から人が入力した値を消しにいくことになる。

        Args:
            rows_by_tab: タブ名 → 行（列名をキーにした辞書）のリスト
        Returns:
            書き込んだ行数
        """
        rows_by_tab = {t: r for t, r in rows_by_tab.items() if r}
        if not rows_by_tab:
            return 0
        self._require_write(f"{sum(len(r) for r in rows_by_tab.values())}件の追記")

        spec = self.spec

        # values().append() は使わない。
        #
        # append は範囲から「テーブル」を自動検出して書き込み位置を決めるが、
        # **先頭列が非表示だとその列を飛ばす**（実測。A列を隠すと1つ右にずれた）。
        # 暗黙の推測に任せず、書き込む行を自分で決めて明示的に指定する。
        #
        # 全列を読むのは、人が右側の列だけに書いた行を潰さないため。
        existing = execute(
            self._api.values().batchGet(
                spreadsheetId=self.spreadsheet_id,
                ranges=[f"'{t}'!A:{spec.last_column}" for t in rows_by_tab],
            )
        )
        next_rows = {
            tab: len(r.get("values", [])) + 1
            for tab, r in zip(rows_by_tab, existing.get("valueRanges", []))
        }

        # グリッドが足りなければ先に広げる。update は append と違い
        # 範囲外に自動で伸びてくれない
        grow = []
        for tab, rows in rows_by_tab.items():
            needed = next_rows[tab] + len(rows) - 1
            current = self._row_count(tab)
            if needed > current:
                grow.append(
                    {
                        "appendDimension": {
                            "sheetId": self._tab_id(tab),
                            "dimension": "ROWS",
                            "length": needed - current,
                        }
                    }
                )
        if grow:
            execute(
                self._api.batchUpdate(
                    spreadsheetId=self.spreadsheet_id, body={"requests": grow}
                )
            )
            self._invalidate()

        data = []
        written = 0
        for tab, rows in rows_by_tab.items():
            values = [
                [
                    row.get(col, spec.initial_values.get(col, ""))
                    for col in spec.written_columns
                ]
                for row in rows
            ]
            data.append({"range": f"'{tab}'!A{next_rows[tab]}", "values": values})
            written += len(values)

        execute(
            self._api.values().batchUpdate(
                spreadsheetId=self.spreadsheet_id,
                body={"valueInputOption": "RAW", "data": data},
            )
        )
        return written

    def apply_layout(self, tabs: List[str]) -> None:
        """保護・非表示・色・プルダウン・フィルタを全タブ分まとめて適用する。

        冪等なので何度呼んでもよい。追記でグリッドが伸びた分にも書式を
        行き渡らせるため、書き込みのたびに呼ぶ。

        `tabs` に無いタブ名が混じっていても黙って飛ばす。
        """
        by_title = {s["properties"]["title"]: s for s in self._meta()["sheets"]}
        requests: List[dict] = []
        for tab in tabs:
            sheet_meta = by_title.get(tab)
            if sheet_meta is None:
                continue
            requests += layout.requests_for(
                self.spec, sheet_meta, self.service_account_email
            )

        if not requests:
            return
        self._require_write(f"書式の適用 {tabs}")

        execute(
            self._api.batchUpdate(
                spreadsheetId=self.spreadsheet_id, body={"requests": requests}
            )
        )
        self._invalidate()
