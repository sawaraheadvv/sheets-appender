# sheets-appender

**列の所有権を分けた表**を Google スプレッドシートで維持する共通ライブラリ。

左側を機械が持ち、右側を人が持つ。機械は追記と自分の列の更新だけを行い、
**人が書いた列には絶対に触らない。行の移動・削除・並べ替えもしない。**

```
A    B     C      │ D         E     F
ID   名前  登録日  │ ステータス 担当  メモ
─────────────────┼──────────────────────
 機械が書く・保護   │  人が書く・機械は触らない
```

バッチが毎月データを足していく一方で、人が同じ表に進捗を書き込む、という使い方のためのもの。

## インストール

各アプリの `requirements.txt` に追加する（タグで版を固定する）。

```
sheets-appender @ git+https://github.com/sawaraheadvv/sheets-appender@v1.0.0
```

## 使い方

列の形を `SheetSpec` で宣言して `Sheet` に渡す。

```python
from sheets_appender import Sheet, SheetSpec

SPEC = SheetSpec(
    machine_columns=["ID", "名前", "登録日"],
    human_columns=["ステータス", "担当", "メモ"],
    hidden_columns=["ID"],
    column_widths={"名前": 240},
    dropdowns={"ステータス": ["未着手", "進行中", "完了"]},
    initial_values={"ステータス": "未着手"},
    skip_tabs=frozenset({"集計", "README"}),
)

sheet = Sheet(SPEC, spreadsheet_id)       # 既定は読み取り専用
already = sheet.existing_keys()           # A列のキーを集める

sheet = Sheet(SPEC, spreadsheet_id, writable=True)
sheet.ensure_tabs(["2026-10"])
sheet.append_many({"2026-10": [{"ID": "1", "名前": "..."}]})
sheet.apply_layout(["2026-10"])           # 冪等。書き込みのたびに呼ぶ
```

### `SheetSpec`

| 項目 | 既定 | 内容 |
|---|---|---|
| `machine_columns` | 必須 | 機械が書く列。**A列が行の一意キー** |
| `human_columns` | `[]` | 人が書く列 |
| `hidden_columns` | `[]` | 隠す列。データとしては残る |
| `column_widths` | `{}` | 列幅（ピクセル） |
| `dropdowns` | `{}` | `{列名: 選択肢}` |
| `initial_values` | `{}` | **行を作るときだけ**機械が入れる値 |
| `skip_tabs` | `frozenset()` | データが入っていないタブ名（集計など） |
| `palette` | 既定の配色 | 所有権を示す色（→ `Palette`） |
| `protection_note` | `"自動更新される列。手で編集しない"` | 保護範囲の説明 |
| `extra_layout` | `None` | `(spec, tab_id) -> list[dict]`。条件付き書式などを足す |

**`initial_values` は `human_columns` の先頭から連続している必要がある。**
飛んだ位置を許すと、間の列を空文字で上書きしてしまうため。

### メソッド

| 読み取り | |
|---|---|
| `tab_names()` | 全タブ名 |
| `data_tabs()` | `skip_tabs` を除いたタブ名 |
| `existing_keys(tabs=None)` | A列のキーの集合。既定は全データタブ |
| `read_rows(tabs)` | `{タブ名: 行のリスト}`。列数を揃え、キーの無い行を落とす |
| `column_values(tab, name)` | 1タブの1列 |

| 書き込み（`writable=True` が必要） | |
|---|---|
| `ensure_tabs(tabs)` | 無いタブを作りヘッダを書く。**既存タブのヘッダは触らない** |
| `append_many({タブ: [行]})` | 末尾に追記する。書き込んだ行数を返す |
| `apply_layout(tabs)` | 保護・非表示・色・プルダウン・フィルタ。冪等 |
| `rename_tab(old, new)` / `delete_tab(tab)` | |

### 必要な環境変数

| 変数 | 内容 |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_KEY` | サービスアカウント鍵のJSONの中身 |
| `GOOGLE_SERVICE_ACCOUNT_KEY_FILE` | 鍵ファイルのパス（`key_path=` 引数でも指定可） |

**対象のスプレッドシートに、サービスアカウントのメールアドレスを編集者として
共有しておく必要がある。** 要求するスコープは `spreadsheets` だけで、
共有されたシート以外には触れない。

GitHub Actions では Secrets に登録して `env:` で渡す。
環境変数ファイル（dotenv）はこのライブラリでは読まないので、必要なら利用側で読み込むこと。

## 挙動

### 既定では書き込めない

`writable=True` を明示しない限り、追記・タブ作成・書式適用・タブ削除はすべて
`ReadOnlyError` になる。人が作業中のシートをうっかり書き換えないため。

**0件の追記と、既にあるタブへの `ensure_tabs` は例外にならない**（何もしないので）。
「追加なし」で落ちると使いづらいため。

なぜ閉じているかを説明したいときは `read_only_note` を渡す。エラーの末尾に出る。

```python
Sheet(SPEC, sid, writable=False, read_only_note="移行中のため閉じています")
```

### 人の列を守るための約束

- **書き込むのは `machine_columns` ＋ `initial_values` の範囲だけ。** そこから右は
  空のまま残す。空文字を書くと、後から人が入力した値を消しにいくことになる
- **追記は必ず末尾の空行から。** 行番号を自分で計算して範囲を明示する
- **既存タブのヘッダは書き換えない。** 人が列を足しているかもしれない
- `apply_layout` は保護・プルダウンを**消して張り直す**。列構成を変えても追随できる

### 実際に踏んだ4つの罠への対処

1. **非表示列があると `values().append()` が列をずらす**
   （A列を隠すと全データが1つ右にずれた）→ `append` を使わず `update` で行を明示する
2. **保護の `editors` を省略すると「シートの編集者全員」が既定になり無効化される**
   → サービスアカウントだけに明示的に絞る
3. **`append(INSERT_ROWS)` は直上行の書式を継ぎ、`values().clear()` は書式を消さない**
   → 実行のたびに本文の書式を正規化する。列の末尾まで塗るので追記分にも乗る
4. **表示列だけにフィルタを張ると、並べ替えで範囲外の列が取り残される**
   （14列のうち B〜I だけをソートすると A と J〜N が元の行に残り、キーと入力内容の
   対応が壊れた）→ フィルタは必ず全列に張る

### API の上限

Sheets API はユーザーあたり**毎分60リクエスト**（読み・書きそれぞれ）。
タブ単位でループすると12タブで超えるので、**全タブ分を1リクエストにまとめる**のを原則にしている。
メタデータもタブ構成が変わるまで使い回す。
429・5xx は指数バックオフで最大6回まで再試行する。

### 制約

- **列は26（Z列）まで。** AA以降のA1記法に未対応。超えると `last_column` が
  `ValueError` を投げる
- **A列が一意キーであることが前提。** 重複判定・既出力の照合はすべてA列を見る

## 開発

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"
.venv/bin/pytest
```

**テストは通信しない。** Sheets API を丸ごと偽物に差し替えて、
組み立てたリクエストの中身を検査している（`tests/conftest.py`）。
`layout.requests_for()` がリクエストのリストを返すだけの純関数になっているのは、
書式の組み立てを通信なしで確かめられるようにするため。
