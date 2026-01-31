---
name: uui
description: |
  UI Toolkit ドメインスキル。ビジュアルツリー検査と開発イテレーション（作成→Play確認→修正ループ）を提供する。UXML/USS/C# によるUI構築からランタイム確認まで。
  Use for: "UI確認", "UIツリー", "UI Toolkit検査", "UI作って", "UI修正して", "UIレイアウト", "VisualElement調べて"
user-invocable: true
---

# Unity UI Toolkit

UI Toolkit によるUI開発を支援する。ツリー検査と開発イテレーションの2つのフローを提供。

## CLI Setup

```bash
u <command>
```

## Decision Criteria

| 状況 | 使うフロー |
|------|-----------|
| UIが表示されない/崩れている | Inspection Flow |
| 新しいUIを作りたい | Development Iteration Flow |
| 既存UIのスタイルを調整したい | Development Iteration Flow |
| 特定要素のプロパティを確認したい | Inspection Flow → inspect |

## Inspection Flow

UI構造やスタイルの問題を調査する。

```
UI Issue / Layout Question
  │
  ▼
┌─────────────────────────────┐
│ Step 1: Panel Discovery     │
│ u uitree dump               │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ Step 2: Tree Overview       │
│ u uitree dump -p <panel>    │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ Step 3: Element Query       │
│ u uitree query -p <panel>   │
│   -t/-n/-c (絞り込み)       │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ Step 4: Detail Inspection   │
│ u uitree inspect <ref_id>   │
│   --style --children        │
└──────────┬──────────────────┘
           ▼
      Analyze & Report
```

### Panel Discovery

```bash
u uitree dump                 # パネル一覧
```

ランタイム UI は通常 `GameView`。エディタ拡張は `InspectorWindow` 等。

### Tree Overview

```bash
u uitree dump -p "GameView"            # テキスト形式
u uitree dump -p "GameView" -o json    # JSON形式
u uitree dump -p "GameView" -d 3       # 深さ3まで
```

各要素には `ref_N` の ID が付与される。

### Element Query

AND条件で組み合わせ可能:

```bash
u uitree query -p "GameView" -t Button              # タイプ
u uitree query -p "GameView" -n "StartBtn"           # 名前
u uitree query -p "GameView" -c "primary-button"     # USSクラス
u uitree query -p "GameView" -t Button -c "primary"  # 複合
```

### Detail Inspection

```bash
u uitree inspect ref_3                     # 基本情報
u uitree inspect ref_3 --style             # resolvedStyle 込み
u uitree inspect ref_3 --children          # 子要素込み
u uitree inspect ref_3 --style --children  # 両方
```

| フィールド | 内容 |
|-----------|------|
| type, name, classes | 要素の識別情報 |
| visible, enabledSelf | 表示/有効状態 |
| layout | ローカル座標 (x, y, width, height) |
| worldBound | グローバル座標 |
| resolvedStyle | 計算済みスタイル (--style 時) |
| children | 子要素リスト (--children 時) |

## Development Iteration Flow

UI の作成→Play 確認→修正を繰り返す開発サイクル。

```
Edit UI (UXML/USS/C#)
  │
  ▼
┌─────────────────────────────┐
│ Step 1: Compile & Play      │
│ u refresh                   │
│ u state (poll isCompiling)  │
│ u console get -l E          │
│ u play                      │
│ u state (poll isPlaying)    │
└──────────┬──────────────────┘
           ▼
      compile error? ──yes──► Fix & restart
           │
           no
           ▼
┌─────────────────────────────┐
│ Step 2: Visual Check        │
│ u uitree dump -p "GameView" │
│ u uitree query / inspect    │
│ u screenshot -s game        │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ Step 3: User Feedback       │
│ スクリーンショットとツリー   │
│ 情報を提示しフィードバック待ち│
└──────────┬──────────────────┘
           ▼
      OK? ──yes──► u stop → Done
           │
           no
           ▼
      u stop → Edit → Step 1
```

### Step 1: Compile & Play

```bash
u refresh
u state          # isCompiling == false まで 2秒間隔ポーリング（最大30秒）
u console get -l E
```

コンパイルエラーがなければ:

```bash
u play
u state          # isPlaying == true まで（最大10秒）
```

### Step 2: Visual Check

Play Mode 中にUIの状態を確認:

```bash
u uitree dump -p "GameView" -d 3              # ツリー構造
u uitree query -p "GameView" -t Label         # 特定要素を検索
u uitree inspect ref_N --style                # スタイル詳細
u screenshot -s game -p ./ui_check.png        # スクリーンショット
```

### Step 3: User Feedback

スクリーンショットとツリー情報をユーザーに提示し、修正指示を待つ。自動修正は行わない。

修正が必要なら `u stop` で Play Mode を終了し、コードを修正して Step 1 に戻る。

## Investigation Patterns

### レイアウト問題

```bash
u uitree dump -p "GameView" -d 2
u uitree query -p "GameView" -c "broken-layout"
u uitree inspect ref_N --style
```

確認ポイント: width/height が 0、display: none、visibility: hidden。

### 要素が見つからない

```bash
u uitree query -p "GameView" -n "Button"     # 名前で広く
u uitree query -p "GameView" -t Button       # タイプで
u uitree dump -p "GameView" -o json          # 全ツリー
```

### スタイル競合

```bash
u uitree inspect ref_N --style               # 対象
u uitree inspect ref_parent --style          # 親
u uitree inspect ref_sibling --style         # 兄弟
```

親の flex-direction, align-items, justify-content が子のレイアウトに影響していないか確認。

## Anti-Patterns

| パターン | 問題 | 対策 |
|---------|------|------|
| Play 中にコード修正 | 変更が反映されない | stop → 修正 → play |
| 毎回フルツリーダンプ | トークン浪費 | `-d 2` + query で絞り込む |
| --style を常時付与 | 出力が巨大 | 必要な時だけ |
| ref ID の再利用 | Play 再開で ID が変わる | Play ごとに再取得 |

## Token-Saving Strategies

| 状況 | 対応 |
|------|------|
| ツリーが巨大 | `-d 2` で浅く取得、必要部分だけ深掘り |
| JSON出力が冗長 | テキスト形式 (デフォルト) を使う |
| resolvedStyle が長い | 必要な時だけ `--style` を付ける |
| query結果が多い | 複合条件 (-t + -c) で絞り込む |
| イテレーション中 | 前回と差分がある部分だけ再検査 |

## Related Skills

| スキル | 使い分け |
|--------|---------|
| /uverify | UIコード修正後のコンパイルエラーが解決しない場合 |
| /udebug | UI操作時のランタイムエラー（NullRef等）を調査する場合 |
