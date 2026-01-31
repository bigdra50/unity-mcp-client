---
name: uverify
description: |
  C#スクリプト編集後のビルド検証ワークフロー。refresh→コンパイル待機→エラーチェック→EditModeテスト→ランタイムチェックを一連で実行し、エラー時は修正ループを回す。
  Use for: "ビルド検証", "スクリプト変更を検証", "コンパイル確認してテストして", "実装を検証", "verify"
user-invocable: true
---

# Unity Verification Workflow

C#スクリプト編集後の検証を一連で実行するワークフロー。

## CLI Setup

```bash
# グローバルインストール済みの場合
u <command>

# uvx 経由（インストール不要）
uvx --from git+https://github.com/bigdra50/unity-cli u <command>
```

以下のワークフロー内では `u` コマンドを使用する。

## Full Verification Flow

```
Edit C#
  │
  ▼
┌─────────────────────────┐
│ Step 1: Refresh & Wait  │
│ u refresh               │
│ u state (poll until     │
│   isCompiling == false) │
└──────────┬──────────────┘
           ▼
┌─────────────────────────┐
│ Step 2: Error Check     │
│ u console clear         │
│ u console get -l E      │
└──────────┬──────────────┘
           ▼
      errors? ──yes──► Fix & goto Step 1 (max 3 rounds)
           │
           no
           ▼
┌─────────────────────────┐
│ Step 3: EditMode Tests  │
│ u tests run edit        │
└──────────┬──────────────┘
           ▼
      failures? ──yes──► Fix & goto Step 1 (max 3 rounds)
           │
           no
           ▼
┌─────────────────────────┐
│ Step 4: Runtime Check   │
│ u console clear         │
│ u play                  │
│ u state (poll until     │
│   isPlaying == true)    │
│ wait 3s                 │
│ u console get -l +E+X   │
│ u stop                  │
└──────────┬──────────────┘
           ▼
      Report Results
```

## Step Details

### Step 1: Refresh & Compile Wait

```bash
u refresh
```

refresh 後、コンパイル完了を待つ:

```bash
u state
# isCompiling が true の間、2秒間隔でポーリング
# 最大30秒待機。超えたらタイムアウトとして報告
```

### Step 2: Console Error Check

```bash
u console clear
u console get -l E
```

- `-l E`: Error以上のログを取得
- エラーが0件ならStep 3へ
- エラーがあればファイル・行番号を特定して修正 → Step 1に戻る

エラー出力が多い場合:

```bash
u console get -l E -c 5    # 最初の5件だけ取得
```

### Step 3: EditMode Tests

```bash
u tests run edit
```

テスト結果を確認し:
- 全パス → Step 4へ
- 失敗あり → 失敗テストの内容を確認して修正 → Step 1に戻る

特定テストのみ実行する場合:

```bash
u tests run edit -n "MyNamespace.MyTest"
```

### Step 4: Runtime Check

Play Modeに入り、ランタイムエラーを検出する:

```bash
u console clear
u play
```

Play Mode に入ったことを確認:

```bash
u state
# isPlaying が true になるまでポーリング（最大10秒）
```

3秒待機してランタイムエラーを確認:

```bash
u console get -l +E+X
```

確認が終わったら停止:

```bash
u stop
```

ランタイムエラーが検出された場合はエラー内容を報告する。自動修正は行わず、ユーザーに判断を委ねる。

## Fix Loop Rules

- 各ステップの修正ループは最大3回
- 3回修正しても解決しない場合、現状のエラー内容をまとめてユーザーに報告し、指示を仰ぐ
- 修正後は必ず Step 1 (refresh) からやり直す

## Token-Saving Strategies

コンソールログが大量の場合、トークン消費を抑える:

| 状況 | 対応 |
|------|------|
| エラーが大量 | `-c 5` で最初の5件に絞る |
| 同一エラーの繰り返し | 最初の1件を修正後、再検証 |
| Warning が大量 | `-l +E+X` でError/Exceptionのみに絞る |
| スタックトレース不要 | `-v` フラグを付けない（デフォルトで省略） |

## Auto-trigger Guidelines

以下の操作の後、自動的にこのワークフローを実行する:

- `.cs` ファイルの編集
- `.shader` / `.compute` ファイルの編集
- `.asmdef` / `.asmref` ファイルの編集
- `package.json` / `manifest.json` の編集（Unity パッケージ関連）

ただし以下の場合はスキップする:

- コメントのみの変更
- Unity プロジェクト外のファイル変更
- ユーザーが明示的にスキップを指示した場合

## Result Report Format

検証完了時、以下の形式で報告する:

```
## Verification Result

- Compilation: OK / NG (error count)
- EditMode Tests: OK (passed/total) / NG (failed/total)
- Runtime Check: OK / NG (error count)
- Fix Rounds: N/3 used
```
