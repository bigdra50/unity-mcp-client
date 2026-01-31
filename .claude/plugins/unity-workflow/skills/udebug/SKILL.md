---
name: udebug
description: |
  Unityランタイムエラーのデバッグ調査ワークフロー。コンソールログ分析→シーン階層確認→GameObject/Component検査→スクリーンショット記録の手順でエラー原因を特定する。
  Use for: "バグ調べて", "エラー原因を特定", "ランタイムエラー", "NullReference", "デバッグ", "debug"
user-invocable: true
---

# Unity Debug Workflow

ランタイムエラーや不具合の原因を調査するワークフロー。

## CLI Setup

```bash
u <command>
```

## Investigation Flow

```
Error Report / Bug Reproduction
  │
  ▼
┌─────────────────────────────┐
│ Step 1: Error Capture       │
│ u console get -l E -v       │
│ (stack trace 付き)          │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ Step 2: Error Classification│
│ → NullRef / Missing / CS   │
│ → file:line を特定         │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ Step 3: Context Gathering   │
│ u scene hierarchy           │
│ u gameobject find <name>    │
│ u component inspect         │
└──────────┬──────────────────┘
           ▼
┌─────────────────────────────┐
│ Step 4: State Recording     │
│ u screenshot -s game        │
│ u selection                 │
└──────────┬──────────────────┘
           ▼
      Analyze & Report
```

## Step Details

### Step 1: Error Capture

スタックトレース付きでエラーログを取得:

```bash
u console get -l E -v
```

エラーが大量の場合は絞り込む:

```bash
u console get -l E -c 10                          # 最新10件
u console get -l +E+X -f "NullReference"           # NullRef のみ
u console get -l +E+X -f "MissingReference"        # Missing のみ
```

### Step 2: Error Classification

エラーを分類し、調査方針を決定する:

| エラー種別 | 識別パターン | 次のアクション |
|-----------|-------------|---------------|
| NullReferenceException | `NullReference` | 該当オブジェクトの存在確認 (Step 3) |
| MissingReferenceException | `MissingReference` | 破棄済みオブジェクトの参照調査 |
| MissingComponentException | `MissingComponent` | コンポーネント有無の確認 |
| コンパイルエラー (CS####) | `error CS` | ソースコード修正 → /uverify |
| Assembly参照エラー | `.asmdef` | asmdef 設定確認 |
| アセット依存エラー | `Failed to load` | asset deps/refs で依存調査 |

コンパイルエラーの場合は /uverify に切り替える。

### Step 3: Context Gathering

エラーの種別に応じて情報を収集:

シーン階層の把握:

```bash
u scene hierarchy
u scene hierarchy -d 3       # 深さ制限
```

問題の GameObject を特定:

```bash
u gameobject find -n "PlayerController"
```

コンポーネントの状態を確認:

```bash
u component list -t "PlayerController"
u component inspect -t "PlayerController" -T "Rigidbody"
```

アセット依存の調査:

```bash
u asset info Assets/Prefabs/Player.prefab
u asset deps Assets/Prefabs/Player.prefab
u asset refs Assets/Scripts/Player.cs
```

### Step 4: State Recording

現在の状態を記録:

```bash
u screenshot -s game -p ./debug_screenshot.png
u selection
```

Play Mode 中なら追加情報:

```bash
u state                      # isPlaying, isPaused 等
u console get -l +W -c 5     # 直近の Warning も確認
```

## Investigation Rules

- 1回の調査で解決しない場合、収集した情報をまとめてユーザーに報告する
- コード修正が必要な場合は修正後 /uverify を実行
- 推測による修正は避け、エビデンスに基づく
- `console get` のトークンコストに注意: `-c` で件数制限、`-f` でフィルタ

## Token-Saving Strategies

| 状況 | 対応 |
|------|------|
| スタックトレースが長い | `-v` で1回取得し、関連フレームのみ抽出 |
| scene hierarchy が巨大 | `-d 2` で浅く取得、必要な枝だけ深掘り |
| 同一エラーの繰り返し | `-c 1` で1件だけ取得 |

## Result Report Format

調査完了時、以下の形式で報告する:

```
## Debug Report

- Error Type: NullReferenceException
- Location: Assets/Scripts/Player.cs:42
- Root Cause: (特定した原因)
- Affected Objects: (関連 GameObject/Component)
- Fix Suggestion: (修正案)
```
