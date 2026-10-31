"""シートの見た目を組み立てる。APIは呼ばない。

`requests_for()` は Sheets API の batchUpdate に渡すリクエストの**リストを返すだけ**。
実際に送るのは `client.Sheet.apply_layout()` の仕事。分けてあるのは、
組み立てのほうを通信なしで確かめられるようにするため。

ここに入っている4つの対処は、どれも実際に踏んで分かったもの:

  1. 非表示列があると values().append() が列をずらす
     → `client.append_many` が update で行を明示する
  2. 保護の editors を省略すると「シートの編集者全員」が既定になり無効化される
     → サービスアカウントだけに明示的に絞る
  3. append(INSERT_ROWS) は直上行の書式を継ぎ、values().clear() は書式を消さない
     → 実行のたびに本文の書式を正規化する
  4. 表示列だけにフィルタを張ると、並べ替えで範囲外の列が取り残される
     → フィルタは必ず全列に張る
"""

from __future__ import annotations

from typing import List

from .spec import SheetSpec


def requests_for(
    spec: SheetSpec, sheet_meta: dict, service_account_email: str
) -> List[dict]:
    """1タブ分のリクエストを組み立てる。

    `sheet_meta` はスプレッドシートのメタデータの `sheets[]` の1要素。
    既存の保護・条件付き書式を消して張り直すため、中身を見る必要がある。
    """
    tab_id = sheet_meta["properties"]["sheetId"]
    n_machine, n_all = len(spec.machine_columns), len(spec.header)
    palette = spec.palette
    requests: List[dict] = []

    # 既存の保護を消してから張り直す（列構成が変わっても追随できる）
    for protected in sheet_meta.get("protectedRanges", []):
        requests.append(
            {
                "deleteProtectedRange": {
                    "protectedRangeId": protected["protectedRangeId"]
                }
            }
        )

    # 条件付き書式も同じく張り直す。消すのは後ろから（index が詰まるため）。
    # extra_layout を持つシートだけが条件付き書式を持つので、それ以外は触らない
    if spec.extra_layout is not None:
        for i in range(len(sheet_meta.get("conditionalFormats", [])) - 1, -1, -1):
            requests.append(
                {"deleteConditionalFormatRule": {"sheetId": tab_id, "index": i}}
            )

    requests.append(
        {
            "addProtectedRange": {
                "protectedRange": {
                    "range": {
                        "sheetId": tab_id,
                        "startColumnIndex": 0,
                        "endColumnIndex": n_machine,
                    },
                    "description": spec.protection_note,
                    # editors を省略すると「シートの編集者全員」が既定になり、
                    # 保護が意味をなさない。サービスアカウントだけに明示的に絞る
                    "editors": {"users": [service_account_email]},
                    "requestingUserCanEdit": False,
                }
            }
        }
    )

    for name in spec.hidden_columns:
        index = spec.index(name)
        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": tab_id,
                        "dimension": "COLUMNS",
                        "startIndex": index,
                        "endIndex": index + 1,
                    },
                    "properties": {"hiddenByUser": True},
                    "fields": "hiddenByUser",
                }
            }
        )

    # ヘッダ行を固定してスクロールしても見えるようにする
    requests.append(
        {
            "updateSheetProperties": {
                "properties": {
                    "sheetId": tab_id,
                    "gridProperties": {"frozenRowCount": 1},
                },
                "fields": "gridProperties.frozenRowCount",
            }
        }
    )

    # ── 見た目で所有権を示す ────────────────────────────────────
    for start, end, bg, fg in (
        (0, n_machine, palette.machine_header_bg, palette.machine_header_fg),
        (n_machine, n_all, palette.human_header_bg, palette.human_header_fg),
    ):
        if start == end:
            continue
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": tab_id,
                        "startRowIndex": 0,
                        "endRowIndex": 1,
                        "startColumnIndex": start,
                        "endColumnIndex": end,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": bg,
                            "textFormat": {"bold": True, "foregroundColor": fg},
                            "verticalAlignment": "MIDDLE",
                        }
                    },
                    "fields": (
                        "userEnteredFormat(backgroundColor,textFormat,"
                        "verticalAlignment)"
                    ),
                }
            }
        )

    # 本文の背景色と太字を正規化する。
    #
    # append(INSERT_ROWS) は直上行の書式を継ぎ、values().clear() は値しか
    # 消さない。放っておくとヘッダの色と太字が全行に伝播する。
    #
    # endRowIndex を指定せず列の末尾まで塗るので、追記された行にも乗る
    for start, end, color in (
        (0, n_machine, palette.machine_body_bg),
        (n_machine, n_all, palette.human_body_bg),
    ):
        if start == end:
            continue
        requests.append(
            {
                "repeatCell": {
                    "range": {
                        "sheetId": tab_id,
                        "startRowIndex": 1,
                        "startColumnIndex": start,
                        "endColumnIndex": end,
                    },
                    "cell": {
                        "userEnteredFormat": {
                            "backgroundColor": color,
                            "textFormat": {"bold": False},
                        }
                    },
                    "fields": (
                        "userEnteredFormat.backgroundColor,"
                        "userEnteredFormat.textFormat.bold"
                    ),
                }
            }
        )

    # このシートだけの書式
    if spec.extra_layout is not None:
        requests += spec.extra_layout(spec, tab_id)

    # フィルタは必ず全列に張る。
    #
    # 表示列だけに張ると、そのフィルタで並べ替えたときに**範囲内の列しか
    # 動かず、キー列と人が入力した列が置き去りになる**。実測で確認済み:
    # 14列のうち B〜I だけをソートすると A と J〜N が元の行に残り、
    # キーと入力内容の対応が完全に壊れた。
    requests.append(
        {
            "setBasicFilter": {
                "filter": {
                    "range": {
                        "sheetId": tab_id,
                        "startRowIndex": 0,
                        "startColumnIndex": 0,
                        "endColumnIndex": n_all,
                    }
                }
            }
        }
    )

    # プルダウン。
    #
    # 先に人の列全体の入力規則を消す。列の順序を入れ替えたとき、
    # 古い位置に残った規則が別の列に居座るため
    if spec.dropdowns:
        if n_machine < n_all:
            requests.append(
                {
                    "setDataValidation": {
                        "range": {
                            "sheetId": tab_id,
                            "startRowIndex": 1,
                            "startColumnIndex": n_machine,
                            "endColumnIndex": n_all,
                        }
                    }
                }
            )
        for name, choices in spec.dropdowns.items():
            index = spec.index(name)
            requests.append(
                {
                    "setDataValidation": {
                        "range": {
                            "sheetId": tab_id,
                            "startRowIndex": 1,
                            "startColumnIndex": index,
                            "endColumnIndex": index + 1,
                        },
                        "rule": {
                            "condition": {
                                "type": "ONE_OF_LIST",
                                "values": [
                                    {"userEnteredValue": v} for v in choices
                                ],
                            },
                            "showCustomUi": True,
                            # strict にしない。選択肢を増やす前に人が
                            # 手で入れた値を弾いて作業を止めないため
                            "strict": False,
                        },
                    }
                }
            )

    for name, width in spec.column_widths.items():
        index = spec.index(name)
        requests.append(
            {
                "updateDimensionProperties": {
                    "range": {
                        "sheetId": tab_id,
                        "dimension": "COLUMNS",
                        "startIndex": index,
                        "endIndex": index + 1,
                    },
                    "properties": {"pixelSize": width},
                    "fields": "pixelSize",
                }
            }
        )

    return requests
