# 日経Monitor (Nikkei Monitor)

日経225miniをリアルタイムで監視する Python 学習プロジェクトです。
VWAP・CVD などのテクニカル指標でシグナルを生成し、チャートと Windows 通知で結果を確認できます。

> ⚠️ **重要**: このプロジェクトは **自動売買・自動発注機能を持ちません**。表示・分析専用です。

---

## 概要

Yahoo Finance から取得した5分足データをもとに、複数のテクニカル指標を計算して BUY / SELL / WAIT シグナルを生成します。

- ダミーデータは使いません（Yahoo Finance のリアルデータを使用）
- バックテストで過去 60 日間の戦略を検証できます
- チャート画像の出力と Windows デスクトップ通知をサポートしています

---

## 主な機能

| 機能 | 説明 |
|------|------|
| **リアルデータ取得** | Yahoo Finance から `^N225`（日経225指数）を取得 |
| **VWAP** | 出来高加重平均価格。セッションごとにリセット |
| **CVD** | 累積出来高デルタ。買い/売り圧力の累積変化を追跡 |
| **出来高フィルター** | 5本移動平均の 1.5 倍超の出来高がある場合のみシグナル有効 |
| **EMA トレンドフィルター** | EMA(20) より上なら上昇トレンドとみなし BUY を許可 |
| **ATR ボラティリティフィルター** | ATR(14) が低いレンジ相場ではシグナルを出さない（閾値: 30円） |
| **BUY / SELL / WAIT シグナル** | 5条件すべて揃った場合のみシグナル発生（誤シグナルを削減） |
| **チャート出力** | `chart.png` にローソク足・VWAP・シグナルマーカーを保存 |
| **Windows 通知** | BUY / SELL シグナル発生時にデスクトップ通知 |
| **バックテスト** | SL・TP・スリッページ・取引コスト対応の詳細バックテスト |
| **戦略比較** | v1.5（3条件）と v1.6（5条件）のバックテスト結果を並べて比較 |

> **データソースについて**: 日経225mini 先物（OSE 上場）の出来高データは無料 API では取得困難なため、
> `^N225`（日経225指数）を代替として使用しています。
> 出来高は「価格レンジ × 10」で近似（開発用）。
> 実際の先物データ（`NIY=F` など）に切り替えるには `data_source.py` の `TICKER` を変更してください。

---

## シグナル判定ロジック（v1.6）

| シグナル | 条件（5つすべて必要） |
|----------|----------------------|
| **BUY（買い）** | 終値 > VWAP &nbsp;&amp;&amp;&nbsp; CVD > 0 &nbsp;&amp;&amp;&nbsp; 出来高 > 移動平均×1.5 &nbsp;&amp;&amp;&nbsp; 終値 > EMA &nbsp;&amp;&amp;&nbsp; ATR ≥ 30円 |
| **SELL（売り）** | 終値 < VWAP &nbsp;&amp;&amp;&nbsp; CVD < 0 &nbsp;&amp;&amp;&nbsp; 出来高 > 移動平均×1.5 &nbsp;&amp;&amp;&nbsp; 終値 < EMA &nbsp;&amp;&amp;&nbsp; ATR ≥ 30円 |
| **WAIT（見送り）** | 上記以外 |

---

## セットアップ

### 動作環境

- Python 3.10 以上
- Windows OS（デスクトップ通知機能に必要）

### インストール手順

**1. リポジトリをクローン**

```bash
git clone https://github.com/wes1118/nikkei_monitor.git
cd nikkei_monitor
```

**2. 仮想環境を作成（推奨）**

```bash
python -m venv .venv
.venv\Scripts\activate
```

**3. 依存パッケージをインストール**

```bash
pip install -r requirements.txt
```

---

## 使い方

### リアルタイム監視

```bash
python main.py
```

実行すると以下の順で処理されます:

1. Yahoo Finance から最新の5分足データを取得（最大 40 本）
2. VWAP・出来高移動平均・CVD・EMA・ATR を計算
3. BUY / SELL / WAIT シグナルを判定
4. ターミナルにカラー表示
5. `chart.png` を保存
6. BUY または SELL シグナルの場合、Windows デスクトップ通知

### バックテスト

```bash
python backtest.py
```

過去 60 日間のデータでシグナル戦略をシミュレーションします。
ストップロス（SL）・テイクプロフィット（TP）・スリッページ・取引コストを考慮した詳細な分析が可能です。
結果は `backtest_report.txt` に保存されます。

**デフォルト設定:**

| 項目 | 設定値 |
|------|--------|
| ストップロス | 150 円 |
| テイクプロフィット | 300 円 |
| スリッページ | 10 円 / 片道 |
| 取引コスト | 20 円 / トレード |
| 合計コスト（往復） | 40 円 / トレード |

### 戦略比較

```bash
python compare.py
```

v1.5（3条件）と v1.6（5条件）のバックテスト結果を同じ期間・設定で比較します。
結果は `strategy_comparison.txt` に保存されます。

---

## ファイル構成

```
nikkei_monitor/
├── main.py                    # メインスクリプト（監視・表示）
├── data_source.py             # Yahoo Finance からデータ取得
├── indicators.py              # テクニカル指標の計算（VWAP / CVD / EMA / ATR）
├── strategy.py                # シグナル判定ロジック（v1.6 現行版 + v1.5 比較用）
├── chart.py                   # チャート生成（日本語フォント対応 / 英語フォールバック）
├── notifier.py                # Windows デスクトップ通知
├── backtest.py                # バックテスト（SL / TP / コスト対応）
├── compare.py                 # 戦略比較（v1.5 vs v1.6）
├── requirements.txt           # 依存パッケージ一覧
├── chart.png                  # 生成されたチャート（初回実行後に作成）
├── backtest_report.txt        # バックテスト結果（UTF-8 BOM付き）
└── strategy_comparison.txt    # 戦略比較結果（UTF-8 BOM付き）
```

---

## バージョン履歴

| バージョン | 内容 |
|-----------|------|
| **v1.0** | MVP — ターミナル表示・VWAP / CVD / 出来高移動平均・シグナル判定 |
| **v1.1** | チャート出力 — `chart.png` 生成 |
| **v1.2** | Windows 通知 — BUY / SELL 時にデスクトップ通知 |
| **v1.3** | リアルデータ — Yahoo Finance（`yfinance`）からデータ取得 |
| **v1.4** | バックテスト — `backtest.py` で 60 日間の過去データを検証 |
| **v1.5** | バックテスト強化 — SL / TP / スリッページ / 取引コスト / 最大ドローダウン / 連勝連敗 |
| **v1.6** | シグナル改善 — EMA トレンドフィルター・ATR ボラティリティフィルター・出来高 1.5 倍・戦略比較スクリプト |
| **v1.7** | 日本語対応強化 — チャートの日本語フォント自動検出・README 日本語化・レポートファイル BOM 対応 |

---

## 今後の予定（ロードマップ）

- **LINE Messaging API 通知** — スマートフォンに LINE でシグナルを通知
- **AI 判断エンジン** — 言語モデルによるシグナルへのコメント・解説生成

---

## 依存パッケージ

```
pandas
tabulate
colorama
matplotlib
yfinance
```

```bash
pip install -r requirements.txt
```
