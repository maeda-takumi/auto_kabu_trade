# kabuステーションAPI 発注まわりまとめ

更新日: 2026-04-20

この資料は **kabuステーションAPI のうち、特に発注まわり** をわかりやすく整理したものです。  
特に以下を重点的にまとめています。

- 新規注文の出し方
- 逆指値を使ったロスカット注文の出し方
- 利確に使う指値注文の出し方
- 信用返済（決済）注文の出し方
- 実装時によくハマるポイント

---

## 1. まず全体像

kabuステーションAPI の株式向け発注は、基本的に以下の流れです。

1. kabuステーションを起動してログインする
2. `/token` で API トークンを取得する
3. 取得したトークンを `X-API-KEY` ヘッダに付ける
4. `/sendorder` に JSON を POST して発注する
5. `/orders` で注文状況確認、`/positions` で建玉確認をする

本番URL:

- `http://localhost:18080/kabusapi`

検証URL:

- `http://localhost:18081/kabusapi`

**注意点**

- 発注系は秒間5件ほどの流量制限があります。
- トークンは毎回取り直す必要はありませんが、以下で無効になります。  
  - kabuステーション終了時  
  - kabuステーションからログアウト時  
  - 別トークン発行時  
  - 早朝の強制ログアウト時

---

## 2. トークン取得

### エンドポイント

`POST /token`

### 例

```python
import requests

BASE_URL = "http://localhost:18080/kabusapi"
API_PASSWORD = "あなたのAPIパスワード"

res = requests.post(
    f"{BASE_URL}/token",
    json={"APIPassword": API_PASSWORD},
    headers={"Content-Type": "application/json"}
)
res.raise_for_status()
token = res.json()["Token"]
print(token)
```

---

## 3. `/sendorder` の基本

### エンドポイント

`POST /sendorder`

### 共通ヘッダ

```python
headers = {
    "Content-Type": "application/json",
    "X-API-KEY": token,
}
```

### 株式注文でよく使う主要パラメータ

| 項目 | 意味 | 主な値 |
|---|---|---|
| `Symbol` | 銘柄コード | 例: `7203` |
| `Exchange` | 市場コード | `1=東証`, `9=SOR`, `27=東証+` |
| `SecurityType` | 商品種別 | `1=株式` |
| `Side` | 売買区分 | `1=売`, `2=買` |
| `CashMargin` | 取引区分 | `1=現物`, `2=信用新規`, `3=信用返済` |
| `MarginTradeType` | 信用種別 | `1=制度`, `2=一般長期`, `3=一般デイトレ` |
| `DelivType` | 受渡区分 | 現物買は必須、信用新規は `0`、信用返済は必須 |
| `FundType` | 預り区分 | 現物売は半角スペース2つ、信用は `11` 推奨 |
| `AccountType` | 口座種別 | `2=一般`, `4=特定`, `12=法人` |
| `Qty` | 数量 | 100 など |
| `FrontOrderType` | 執行条件 | `10=成行`, `20=指値`, `30=逆指値` など |
| `Price` | 価格 | 成行なら `0`、指値なら価格 |
| `ExpireDay` | 有効期限 | `0=本日相当`、または `yyyyMMdd` |

---

## 4. まず覚えるべき3パターン

### 4-1. 現物買い成行

```python
payload = {
    "Symbol": "7203",
    "Exchange": 1,
    "SecurityType": 1,
    "Side": "2",
    "CashMargin": 1,
    "DelivType": 2,
    "FundType": "AA",
    "AccountType": 4,
    "Qty": 100,
    "FrontOrderType": 10,
    "Price": 0,
    "ExpireDay": 0,
}
```

### 4-2. 現物買い指値

```python
payload = {
    "Symbol": "7203",
    "Exchange": 1,
    "SecurityType": 1,
    "Side": "2",
    "CashMargin": 1,
    "DelivType": 2,
    "FundType": "AA",
    "AccountType": 4,
    "Qty": 100,
    "FrontOrderType": 20,
    "Price": 2500.0,
    "ExpireDay": 0,
}
```

### 4-3. 信用新規買い成行

```python
payload = {
    "Symbol": "7203",
    "Exchange": 1,
    "SecurityType": 1,
    "Side": "2",
    "CashMargin": 2,
    "MarginTradeType": 1,
    "DelivType": 0,
    "FundType": "11",
    "AccountType": 4,
    "Qty": 100,
    "FrontOrderType": 10,
    "Price": 0,
    "ExpireDay": 0,
}
```

---

## 5. 利確注文のやり方

「利確」は、基本的には **普通の指値売り** です。

### 現物の利確

たとえば 2,500 円で買った現物を 2,700 円で利確したいなら、

- `CashMargin = 1`（現物）
- `Side = 1`（売）
- `FrontOrderType = 20`（指値）
- `Price = 2700`

です。

```python
payload = {
    "Symbol": "7203",
    "Exchange": 1,
    "SecurityType": 1,
    "Side": "1",
    "CashMargin": 1,
    "DelivType": 0,
    "FundType": "  ",
    "AccountType": 4,
    "Qty": 100,
    "FrontOrderType": 20,
    "Price": 2700.0,
    "ExpireDay": 0,
}
```

### 信用建玉の利確

信用の利確は「返済指値注文」です。  
つまり **信用返済 + 指値** になります。

- `CashMargin = 3`（返済）
- `FrontOrderType = 20`（指値）
- さらに `ClosePositions` または `ClosePositionOrder` が必要

この部分は後述の「決済注文」で詳しく説明します。

---

## 6. ロスカット注文のやり方（逆指値）

ロスカットは、通常 **逆指値** を使います。  
`FrontOrderType = 30` を指定し、`ReverseLimitOrder` を設定します。

### `ReverseLimitOrder` の意味

| 項目 | 意味 |
|---|---|
| `TriggerSec` | 何をトリガにするか (`1=発注銘柄`) |
| `TriggerPrice` | トリガ価格 |
| `UnderOver` | `1=以下`, `2=以上` |
| `AfterHitOrderType` | ヒット後の執行条件 (`1=成行`, `2=指値`, `3=不成`) |
| `AfterHitPrice` | ヒット後価格。成行なら `0` |

---

## 7. 指値指定でロスカット・利確を考えるときの整理

ここが一番混乱しやすいです。

### パターンA: 損切りだけ入れたい

例: 2,500 円で買ったあと、2,420 円を割ったら成行で売りたい

```python
payload = {
    "Symbol": "7203",
    "Exchange": 1,
    "SecurityType": 1,
    "Side": "1",
    "CashMargin": 1,
    "DelivType": 0,
    "FundType": "  ",
    "AccountType": 4,
    "Qty": 100,
    "FrontOrderType": 30,
    "Price": 0,
    "ExpireDay": 0,
    "ReverseLimitOrder": {
        "TriggerSec": 1,
        "TriggerPrice": 2420.0,
        "UnderOver": 1,
        "AfterHitOrderType": 1,
        "AfterHitPrice": 0
    }
}
```

意味:

- 株価が **2420円以下** になったら
- **成行売り** を出す

---

### パターンB: 損切りを逆指値 + ヒット後に指値で出したい

例: 2,420 円以下になったら、2,418 円で売り注文を出したい

```python
payload = {
    "Symbol": "7203",
    "Exchange": 1,
    "SecurityType": 1,
    "Side": "1",
    "CashMargin": 1,
    "DelivType": 0,
    "FundType": "  ",
    "AccountType": 4,
    "Qty": 100,
    "FrontOrderType": 30,
    "Price": 0,
    "ExpireDay": 0,
    "ReverseLimitOrder": {
        "TriggerSec": 1,
        "TriggerPrice": 2420.0,
        "UnderOver": 1,
        "AfterHitOrderType": 2,
        "AfterHitPrice": 2418.0
    }
}
```

意味:

- 2420 円以下でトリガ
- ヒット後は 2418 円の指値売り

---

### パターンC: 上に抜けたら利確したい

例: 2,700 円以上になったら成行で売りたい

```python
payload = {
    "Symbol": "7203",
    "Exchange": 1,
    "SecurityType": 1,
    "Side": "1",
    "CashMargin": 1,
    "DelivType": 0,
    "FundType": "  ",
    "AccountType": 4,
    "Qty": 100,
    "FrontOrderType": 30,
    "Price": 0,
    "ExpireDay": 0,
    "ReverseLimitOrder": {
        "TriggerSec": 1,
        "TriggerPrice": 2700.0,
        "UnderOver": 2,
        "AfterHitOrderType": 1,
        "AfterHitPrice": 0
    }
}
```

意味:

- 2700 円以上でトリガ
- 成行で売る

---

## 8. 「ロスカット値 + 利確値を同時に1回で入れたい」場合

ここは重要です。

### 結論

**通常の `/sendorder`（現物・信用）の基本リクエスト定義を見る限り、1つの発注で「利確指値」と「損切逆指値」を同時に持つ専用フィールドは確認できません。**  
リクエスト定義として公開されているのは、株式向けでは主に以下です。

- 通常注文（成行 / 指値）
- `FrontOrderType = 30` の逆指値
- 信用返済時の `ClosePositions` / `ClosePositionOrder`

つまり、**REST の標準的な `/sendorder` の見た目だけでは、いわゆる OCO 的に「利確と損切を同時セット」する形は分かりやすく公開されていない** です。

### 実務上の考え方

そのため実装では次のどちらかで考えるのが安全です。

1. **先に利確の指値を出し、価格監視は自前でして損切条件で別途注文する**  
2. **約定後に逆指値だけ入れる**  
3. **kabuステーション本体の注文機能でできる注文種別と、REST API の公開定義が一致しているかを別途検証する**

### 実装判断としておすすめ

まずは API では以下の2本立てで組むのが無難です。

- 利確: 普通の指値注文
- 損切: 逆指値注文

ただし、**同一建玉に対して二重約定リスクが出ないよう、注文管理ロジックを自前で入れる** 必要があります。

---

## 9. 決済注文のやり方（信用返済）

信用の決済注文では、普通の新規注文と違って **どの建玉を返済するか** の指定が重要です。

### 返済で必要になる考え方

- `CashMargin = 3` にする
- `MarginTradeType` を建玉に合わせる
- `DelivType` は信用返済では必須
- 建玉指定は次のどちらか
  - `ClosePositionOrder`: 返済順序を指定して自動選択
  - `ClosePositions`: `HoldID` を指定して明示返済

### 注意

`ClosePositionOrder` と `ClosePositions` は **同時指定不可** です。

---

## 10. 決済注文の前に `/positions` で建玉確認する

返済注文を出す前に、まず建玉を確認します。

### 例

```python
res = requests.get(
    f"{BASE_URL}/positions",
    headers={"X-API-KEY": token},
    params={"product": 2, "symbol": "7203"}
)
res.raise_for_status()
positions = res.json()
print(positions)
```

`/positions` のレスポンスで特に大事なのは以下です。

| 項目 | 意味 |
|---|---|
| `ExecutionID` | 約定番号 |
| `Symbol` | 銘柄コード |
| `Exchange` | 市場コード |
| `LeavesQty` | 残数量（保有数量） |
| `HoldQty` | 拘束数量 |
| `Side` | 売買区分 |
| `MarginTradeType` | 信用種別 |
| `ExpireDay` | 返済期日 |

### 実務上の重要ポイント

`ClosePositions` に入れるのは **建玉ID (`HoldID`)** です。  
公式定義の例では **`E` から始まる番号** が建玉IDです。

---

## 11. 決済注文の2つの出し方

## 11-1. `ClosePositionOrder` で返済順を指定する方法

これは「どの建玉を返すかを細かく指定せず、順番ルールで返す」方法です。

代表例:

- `0`: 日付が古い順、損益が高い順
- `1`: 日付が古い順、損益が低い順
- `2`: 日付が新しい順、損益が高い順
- `3`: 日付が新しい順、損益が低い順

### 例: 信用返済の成行

```python
payload = {
    "Symbol": "7203",
    "Exchange": 1,
    "SecurityType": 1,
    "Side": "1",
    "CashMargin": 3,
    "MarginTradeType": 1,
    "DelivType": 2,
    "FundType": "11",
    "AccountType": 4,
    "Qty": 100,
    "ClosePositionOrder": 0,
    "FrontOrderType": 10,
    "Price": 0,
    "ExpireDay": 0,
}
```

---

## 11-2. `ClosePositions` で建玉を明示指定する方法

こちらのほうが実務では分かりやすいです。  
返済したい建玉IDごとに数量を明示できます。

### 例: 建玉IDを指定して返済成行

```python
payload = {
    "Symbol": "7203",
    "Exchange": 1,
    "SecurityType": 1,
    "Side": "1",
    "CashMargin": 3,
    "MarginTradeType": 1,
    "DelivType": 2,
    "FundType": "11",
    "AccountType": 4,
    "Qty": 100,
    "ClosePositions": [
        {
            "HoldID": "E20260420xxxxx",
            "Qty": 100
        }
    ],
    "FrontOrderType": 10,
    "Price": 0,
    "ExpireDay": 0,
}
```

### 例: 建玉IDを指定して返済指値（利確決済）

```python
payload = {
    "Symbol": "7203",
    "Exchange": 1,
    "SecurityType": 1,
    "Side": "1",
    "CashMargin": 3,
    "MarginTradeType": 1,
    "DelivType": 2,
    "FundType": "11",
    "AccountType": 4,
    "Qty": 100,
    "ClosePositions": [
        {
            "HoldID": "E20260420xxxxx",
            "Qty": 100
        }
    ],
    "FrontOrderType": 20,
    "Price": 2700.0,
    "ExpireDay": 0,
}
```

### 例: 建玉IDを指定して返済逆指値（損切決済）

```python
payload = {
    "Symbol": "7203",
    "Exchange": 1,
    "SecurityType": 1,
    "Side": "1",
    "CashMargin": 3,
    "MarginTradeType": 1,
    "DelivType": 2,
    "FundType": "11",
    "AccountType": 4,
    "Qty": 100,
    "ClosePositions": [
        {
            "HoldID": "E20260420xxxxx",
            "Qty": 100
        }
    ],
    "FrontOrderType": 30,
    "Price": 0,
    "ExpireDay": 0,
    "ReverseLimitOrder": {
        "TriggerSec": 1,
        "TriggerPrice": 2420.0,
        "UnderOver": 1,
        "AfterHitOrderType": 1,
        "AfterHitPrice": 0
    }
}
```

---

## 12. 返済注文でハマりやすい点

### 12-1. `ClosePositionOrder` と `ClosePositions` を同時に入れない

同時指定はエラーです。

### 12-2. `DelivType` を省略しない

信用返済は `DelivType` 必須です。  
省略や不整合でエラーになりやすいです。

### 12-3. `Exchange` を建玉の市場と合わせる

公開情報や質問事例では、**返済する建玉の市場に合わせないとエラーになるケース** が見られます。  
特に東証保有建玉を SOR / 東証+ で返せないケースに注意です。

### 12-4. `Qty` と `ClosePositions[].Qty` の整合を取る

返済数量にズレがあるとエラー要因になります。

### 12-5. `Side` は返済対象建玉に対して整合が必要

信用買建玉を返済するなら売、信用売建玉を返済するなら買、という整合が必要です。

---

## 13. 実際の送信コードのひな形

```python
import requests

BASE_URL = "http://localhost:18080/kabusapi"
TOKEN = "取得済みトークン"

headers = {
    "Content-Type": "application/json",
    "X-API-KEY": TOKEN,
}

payload = {
    "Symbol": "7203",
    "Exchange": 1,
    "SecurityType": 1,
    "Side": "2",
    "CashMargin": 1,
    "DelivType": 2,
    "FundType": "AA",
    "AccountType": 4,
    "Qty": 100,
    "FrontOrderType": 20,
    "Price": 2500.0,
    "ExpireDay": 0,
}

res = requests.post(
    f"{BASE_URL}/sendorder",
    headers=headers,
    json=payload,
)

print(res.status_code)
print(res.text)
```

---

## 14. よくあるエラー

### `4001005 パラメータ変換エラー`

よくある原因:

- kabuステーションの「システム設定 > 注文1」とAPI指定値の不整合
- 返済注文で `DelivType` や `ClosePositions` が不正
- 市場コードの不一致

### `4002010 パラメータ不正: DelivType`

- 現物買なのに指定がない
- 信用返済なのに指定がない
- 現物売なのに `0` 以外を入れている

### `4002011 パラメータ不正: FundType`

- 現物売で半角スペース2つになっていない
- 信用なのに `11` 以外を入れている

### `4002012 パラメータ不正: FrontOrderType`

- 執行条件と市場の組み合わせ不正
- 逆指値時の指定不整合

### `Result = 8 返済建玉情報不正エラー`

- `HoldID` や数量、売買区分が返済対象と合っていない

---

## 15. 実装のおすすめ方針

### まず最初に作るべき機能

1. トークン取得
2. 現物成行
3. 現物指値
4. `/positions` 取得
5. 信用返済成行（`ClosePositions` 指定）
6. 返済指値
7. 返済逆指値

この順で作ると、切り分けしやすいです。

### 特におすすめ

信用返済は、最初は `ClosePositionOrder` ではなく **`ClosePositions` で明示指定** のほうがデバッグしやすいです。

---

## 16. 迷ったときの判断表

| やりたいこと | 使い方 |
|---|---|
| 現物を今すぐ買う | `CashMargin=1`, `Side=2`, `FrontOrderType=10` |
| 現物をこの価格で買う | `CashMargin=1`, `Side=2`, `FrontOrderType=20`, `Price=価格` |
| 現物をこの価格で利確したい | `CashMargin=1`, `Side=1`, `FrontOrderType=20`, `Price=価格` |
| 現物をこの価格以下で損切りしたい | `CashMargin=1`, `Side=1`, `FrontOrderType=30`, `ReverseLimitOrder` |
| 信用新規建てしたい | `CashMargin=2` |
| 信用建玉を決済したい | `CashMargin=3` + `ClosePositions` or `ClosePositionOrder` |
| 信用建玉を利確決済したい | `CashMargin=3` + `FrontOrderType=20` |
| 信用建玉を損切決済したい | `CashMargin=3` + `FrontOrderType=30` |

---

## 17. 参考にした主な公式情報

- 公式リファレンス  
  https://kabucom.github.io/kabusapi/reference/index.html
- OpenAPI定義  
  https://raw.githubusercontent.com/kabucom/kabusapi/master/reference/kabu_STATION_API.yaml
- APIコード一覧  
  https://kabucom.github.io/kabusapi/ptal/error.html
- 公式GitHub Issues  
  https://github.com/kabucom/kabusapi/issues

---

## 18. 補足メモ

- 現物売の `FundType` は **半角スペース2つ** です。
- 信用返済は **建玉に合わせた市場コード** を意識したほうが安全です。
- 逆指値では `FrontOrderType=30` にし、価格は `ReverseLimitOrder` 側で考えるのが基本です。
- `ClosePositions` の `HoldID` は、返済建玉IDです。
- まずは **現物 → 信用新規 → 信用返済** の順で段階実装すると事故りにくいです。

