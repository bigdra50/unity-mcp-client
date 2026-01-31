---
name: uasset
description: |
  Unityアセット管理ワークフロー。依存関係の把握、不要アセット検出、参照整合性チェックを行う。パッケージの追加・削除も対応。
  Use for: "依存関係を調べて", "不要アセット", "参照確認", "パッケージ追加", "アセット管理"
user-invocable: true
---

# Unity Asset Management Workflow

アセットの依存関係調査・参照整合性チェック・パッケージ管理を行うワークフロー。

## CLI Setup

```bash
# グローバルインストール済みの場合
u <command>

# uvx 経由（インストール不要）
uvx --from git+https://github.com/bigdra50/unity-cli u <command>
```

以下のワークフロー内では `u` コマンドを使用する。

## Decision Criteria

| 状況 | フロー |
|------|--------|
| 特定アセットの依存先を知りたい | Investigation Flow → Dependency Analysis |
| アセットが他から使われているか確認 | Investigation Flow → Reference Check |
| 不要アセットを探したい | Investigation Flow → 全体スキャン |
| パッケージを追加・削除したい | Package Management |
| ビルドサイズを調べたい | Investigation Flow → Dependency Analysis |
| 参照切れを修復したい | Reference Check → 修正 → /uverify |

## Investigation Flow

```
Request (アセットパスまたは調査対象)
  │
  ▼
┌──────────────────────────────┐
│ Step 1: Asset Info           │
│ u asset info <path>          │
│ (型・サイズ・GUID 確認)     │
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│ Step 2: Dependency Tree      │
│ u asset deps <path>          │
│ (依存先を再帰的に取得)      │
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│ Step 3: Reference Check      │
│ u asset refs <path>          │
│ (参照元を取得)              │
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│ Step 4: Problem Detection    │
│ 参照切れ・未使用を判定      │
└──────────┬───────────────────┘
           ▼
      Report
```

## Step Details

### Step 1: Asset Info

対象アセットの基本情報を取得する:

```bash
u asset info Assets/Prefabs/Player.prefab
```

出力例: アセット型、ファイルサイズ、GUID、インポート設定など。

複数アセットを調べる場合は個別に実行:

```bash
u asset info Assets/Materials/PlayerMat.mat
u asset info Assets/Textures/PlayerTex.png
```

### Step 2: Dependency Analysis

再帰的に依存先を取得:

```bash
u asset deps Assets/Prefabs/Player.prefab
```

依存ツリーが深い場合は直接依存のみに絞る:

```bash
u asset deps Assets/Prefabs/Player.prefab --no-recursive
```

依存ツリーの構築パターン:

```
Player.prefab
├── PlayerMat.mat
│   ├── PlayerTex.png
│   └── PlayerShader.shader
├── PlayerAnimator.controller
│   └── IdleClip.anim
└── PlayerScript.cs
```

調査の進め方:
1. `asset deps` で全依存を取得
2. 不審なアセット（サイズが大きい、想定外の参照）を特定
3. 該当アセットに対して `asset info` で詳細確認

### Step 3: Reference Check

アセットがどこから参照されているか確認:

```bash
u asset refs Assets/Textures/PlayerTex.png
```

参照元がない場合、そのアセットは未使用の可能性がある。

参照整合性チェックの手順:

```
対象アセット
  │
  ├── refs で参照元取得
  │     ├── 参照元あり → 使用中
  │     └── 参照元なし → 未使用候補
  │
  └── deps で依存先取得
        ├── 依存先が存在 → 正常
        └── 依存先が欠損 → 参照切れ
```

参照切れの確認:
1. `asset deps` で依存アセット一覧を取得
2. 各依存アセットに対して `asset info` で存在確認
3. 存在しないアセットがあれば参照切れとして報告

### Step 4: Problem Detection

検出パターン:

| 問題 | 判定方法 | 対処 |
|------|----------|------|
| 未使用アセット | `refs` の結果が空 | 削除を検討 |
| 参照切れ | `deps` の結果に欠損アセット | 再割り当てまたは削除 |
| 重複アセット | 同名・同サイズのアセットが複数 | 統合を検討 |
| 過大アセット | `info` でサイズ確認 | インポート設定の最適化 |

## Package Management

### パッケージ一覧の確認

Relay 経由（Unity Editor 接続時）:

```bash
u package list
```

ファイルベース（Relay 不要）:

```bash
u project packages
```

### パッケージの追加

```bash
u package add com.unity.textmeshpro@3.0.6
```

バージョン指定なしの場合、最新版がインストールされる:

```bash
u package add com.unity.inputsystem
```

Git URL からの追加:

```bash
u package add "https://github.com/user/repo.git#v1.0.0"
```

### パッケージの削除

```bash
u package remove com.unity.textmeshpro
```

### パッケージ操作後の検証

パッケージ変更後は /uverify で検証する:

```
u package add/remove ...
  │
  ▼
/uverify (コンパイル確認 → テスト)
```

## Result Report Format

### 依存関係調査の報告

```
## Asset Investigation Report

- Target: Assets/Prefabs/Player.prefab
- Direct Dependencies: 5
- Total Dependencies: 12 (recursive)
- Issues Found:
  - Missing: Assets/Textures/OldTex.png (referenced by PlayerMat.mat)
  - Unused: Assets/Materials/UnusedMat.mat (0 references)
```

### パッケージ操作の報告

```
## Package Operation Report

- Action: add
- Package: com.unity.inputsystem@1.7.0
- Verification: OK / NG
```

## Anti-Patterns

| NG | 理由 | 対策 |
|----|------|------|
| refs を確認せずアセット削除 | 参照元がある場合に参照切れが発生 | 必ず `refs` で参照元を確認 |
| deps を再帰で全取得 | ツリーが大きいとトークンを大量消費 | まず `--no-recursive` で直接依存を確認 |
| package add 後に検証しない | コンパイルエラーに気付かない | 追加後は /uverify を実行 |
| 未使用判定を refs だけで行う | Resources/Addressables 経由の動的参照を見逃す | ユーザーに動的参照の有無を確認 |
| 大量アセットを一括調査 | トークン消費が膨大になる | 対象を絞って段階的に調査 |

## Token-Saving Strategies

| 状況 | 対応 |
|------|------|
| 依存ツリーが深い | `--no-recursive` で直接依存のみ取得 |
| 大量アセットの調査 | 代表的なアセットを数件調べ、パターンを把握 |
| refs の結果が膨大 | 参照元の種類（Scene/Prefab/Material）で分類して報告 |
| package list が長い | `project packages` でファイルベースの確認に切り替え |

## Related Skills

| スキル | 関係 |
|--------|------|
| uverify | パッケージ変更後・参照切れ修正後のビルド検証 |
| uscene | シーン内オブジェクトのアセット参照確認 |
