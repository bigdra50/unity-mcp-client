# Unity Workflow Skills Roadmap

## 背景

コーディングエージェント（Claude Code等）は Unity Editor を直接操作できない。ビルドの実行、コンソールログの確認、Play Mode の制御、シーン階層の把握といったエディタ操作は、コード編集とは異なるチャネルが必要になる。

unity-cli はこの課題を解決する。TCP経由で Unity Editor と通信し、CLI コマンドとしてエディタ操作を提供する。

```
Agent ──(コード編集)──► ファイルシステム
Agent ──(unity-cli)──► Relay Server ──► Unity Editor
```

unity-workflow プラグインは、unity-cli のコマンドを Unity 開発のワークフローとして組み立て、エージェントに「いつ・何を・どの順序で」実行すべきかの判断基準を提供する。

## 設計原則

[actionbook/rust-skills](https://github.com/actionbook/rust-skills) の設計パターンと [Claude Code 公式ドキュメント](https://code.claude.com/docs/en/skills) のベストプラクティスに基づく。

### 1スキル = 1ドメイン

操作別（検査、イテレーション、デバッグ）ではなくドメイン別（UI Toolkit、ビルド検証、デバッグ）で分割する。同じドメインの異なる操作パターンは1つのスキル内にセクションとして配置。

### Progressive Disclosure

| 層 | 内容 | コスト | タイミング |
|----|------|--------|-----------|
| L1 | name + description | ~100トークン/スキル | 常時 |
| L2 | SKILL.md 本文 | <5kトークン | スキル起動時 |
| L3 | references/ 内ファイル | 任意 | 必要時のみ |

### サイズ制約

- SKILL.md 本文: 500行未満
- description: 1024文字以内
- 全スキルの description 合計: 15,000文字以内

### context: fork は使わない

全スキルがメイン会話で実行される。理由: コード修正 → 検証のループをメインコンテキストで回す必要がある。

### unity-cli 依存と非依存の混在

各スキルは unity-cli コマンドによるエディタ操作と、コードパターン等の純粋な知識を混在させてよい。エージェントが Unity 開発を行う上で必要な情報は、CLI 依存かどうかに関わらず適切なドメインスキルに配置する。

## ドメインマップ

Unity 開発でエージェントが必要とする能力領域:

```
                  unity-cli 依存度
        高 ◄────────────────────► なし

  ┌──────────┬──────────┬──────────┬───────────────┐
  │ ビルド   │ デバッグ  │ UI       │ C# コーディング │
  │ 検証     │ 調査     │ Toolkit  │ パターン       │
  │          │          │          │               │
  │ refresh  │ console  │ uitree   │ MonoBehaviour │
  │ console  │ scene    │ play/stop│ ScriptableObj │
  │ tests    │ gameobj  │ screen-  │ async/await   │
  │ play/stop│ component│ shot     │ UniTask       │
  │          │ screen-  │ +UXML/USS│               │
  │          │ shot     │ 編集     │               │
  ├──────────┼──────────┼──────────┼───────────────┤
  │ シーン   │ アセット  │ プロジェ │ パフォーマンス  │
  │ 構築     │ 管理     │ クト管理 │ 最適化         │
  │          │          │          │               │
  │ scene    │ asset    │ project  │ (Profiler     │
  │ gameobj  │ info     │ info     │  未実装)       │
  │ component│ deps     │ packages │ GC, batching  │
  │ asset    │ refs     │ quality  │ memory        │
  └──────────┴──────────┴──────────┴───────────────┘
```

## スキル構成

### Phase 1: 基盤（v1.0）

3つのコアスキルで Unity 開発の基本サイクルをカバー。

| スキル | ドメイン | 責務 |
|--------|---------|------|
| uverify | ビルド検証 | コンパイル→エラーチェック→テスト→ランタイムチェック。修正ループ付き |
| udebug | ランタイムデバッグ | エラー分類→コンテキスト収集→状態記録→原因分析 |
| uui | UI Toolkit 開発 | ツリー検査 + 開発イテレーション（作成→確認→修正ループ） |

### Phase 2: シーン操作（v1.1）

| スキル | ドメイン | 責務 |
|--------|---------|------|
| uscene | シーン構築・管理 | オブジェクト配置→コンポーネント設定→Prefab化→シーン保存 |

前提: unity-cli に `component modify`（プロパティ変更）と `gameobject active`（SetActive）を追加。

### Phase 3: プロジェクト・知識（v1.2）

| スキル | ドメイン | 責務 |
|--------|---------|------|
| uasset | アセット管理 | 依存関係の把握、不要アセット検出、参照整合性チェック |
| unity-csharp | C# コーディング | Unity API パターン、ライフサイクル、アンチパターン（unity-cli 不要） |

前提: unity-cli に `package list/add/remove` を追加。

### Phase 4: ビルド・パフォーマンス（v2.0）

| スキル | ドメイン | 責務 |
|--------|---------|------|
| ubuild | ビルドパイプライン | ビルド実行、プラットフォーム設定、Addressables |
| uperf | パフォーマンス | プロファイリング、GC 分析、バッチング最適化 |

前提: unity-cli に `build` と `profiler` コマンドを追加（BridgeTool の大規模拡充）。

## 各スキル詳細設計

### uverify（Phase 1）

| 項目 | 内容 |
|------|------|
| トリガー | .cs/.shader/.asmdef/.asmref 編集後、"検証して"、"verify" |
| Auto-trigger | .cs/.shader/.asmdef/.asmref/.compute 編集後に自動実行 |
| 主要コマンド | refresh, state, console get/clear, tests run edit, play, stop |
| 判断分岐 | エラー有→修正ループ(max 3)、テスト失敗→修正ループ(max 3) |
| 出力 | Verification Result（Compilation/Tests/Runtime の OK/NG） |

### udebug（Phase 1）

| 項目 | 内容 |
|------|------|
| トリガー | ランタイムエラー発生、"バグ調べて"、"エラー原因を特定" |
| Auto-trigger | なし（ユーザー指示またはエラー検出時） |
| 主要コマンド | console get -v, scene hierarchy, gameobject find, component inspect, screenshot, asset deps/refs |
| 判断分岐 | エラー種別（NullRef→オブジェクト探索、Missing→アセット依存、CS→uverifyへ） |
| 出力 | Debug Report（Error Type/Location/Root Cause/Fix Suggestion） |

### uui（Phase 1）

| 項目 | 内容 |
|------|------|
| トリガー | "UI確認"、"UIツリー"、"UI作って"、"UI修正して"、.uxml/.uss 編集時 |
| Auto-trigger | .uxml/.uss 編集後、UI関連 .cs 編集後 |
| 主要コマンド | uitree dump/query/inspect, play, stop, state, screenshot, console get, refresh |
| フロー1 | Inspection: パネル一覧→ツリー→クエリ→詳細検査 |
| フロー2 | Iteration: 編集→refresh→play→uitree確認→フィードバック→stop→修正→繰り返し |
| 出力 | UI Inspection Report / イテレーション中は都度フィードバック |

### uscene（Phase 2）

| 項目 | 内容 |
|------|------|
| トリガー | "シーンに配置して"、"オブジェクト作って"、"Prefab化して" |
| Auto-trigger | なし |
| 主要コマンド | scene active/hierarchy/save, gameobject create/modify/delete, component list/add/remove, asset prefab |
| フロー | 現状確認→オブジェクト作成→コンポーネント追加→Transform設定→Prefab化→シーン保存 |
| 必要CLI拡張 | component modify, gameobject active |

### uasset（Phase 3）

| 項目 | 内容 |
|------|------|
| トリガー | "依存関係を調べて"、"不要アセット"、"参照確認" |
| Auto-trigger | なし |
| 主要コマンド | asset info/deps/refs, project packages/assemblies |
| フロー | アセット情報取得→依存ツリー構築→参照元確認→問題検出→報告 |
| 必要CLI拡張 | package list/add/remove |

### unity-csharp（Phase 3）

| 項目 | 内容 |
|------|------|
| トリガー | .cs 編集時に自動参照（user-invocable: false） |
| Auto-trigger | globs: `**/*.cs` |
| unity-cli | 不要 |
| 内容 | MonoBehaviour ライフサイクル、ScriptableObject パターン、UniTask/async パターン、Unity 固有のアンチパターン |
| 備考 | SKILL.md のみで完結。エディタ操作なし |

## unity-cli 拡充ロードマップ

### Phase 2 で必要なコマンド

| コマンド | BridgeTool | 説明 |
|---------|-----------|------|
| `component modify -t <go> -T <type> --prop <name> --value <val>` | component (action: modify) | コンポーネントプロパティの変更 |
| `gameobject active -n <name> --active true/false` | gameobject (action: active) | SetActive の操作 |

### Phase 3 で必要なコマンド

| コマンド | BridgeTool | 説明 |
|---------|-----------|------|
| `package list` | package (action: list) | インストール済みパッケージ一覧（Relay経由） |
| `package add <name>@<version>` | package (action: add) | パッケージ追加 |
| `package remove <name>` | package (action: remove) | パッケージ削除 |

### Phase 4 で必要なコマンド

| コマンド | BridgeTool | 説明 |
|---------|-----------|------|
| `build --target <platform>` | build (action: build) | ビルド実行 |
| `build settings` | build (action: settings) | ビルド設定取得 |
| `profiler start/stop/snapshot` | profiler | プロファイラ制御 |
| `profiler frames --count N` | profiler | フレームデータ取得 |

## スキル内部構成テンプレート

rust-skills のセクション構成を Unity 向けに適用:

```markdown
---
name: <skill-name>
description: |
  <ドメインの説明>
  Use for: "<トリガーフレーズ1>", "<トリガーフレーズ2>", ...
user-invocable: true/false
---

# <Skill Title>

<1行の説明>

## CLI Setup
（unity-cli コマンドのセットアップ方法）

## Workflow Flows
（ドメイン内の各ワークフロー図とステップ詳細）

## Decision Criteria
（判断基準テーブル: いつ何を選ぶか）

## Code Patterns
（C# コードテンプレート。unity-cli 不要な知識）

## Anti-Patterns
（やってはいけないパターンとその理由）

## Token-Saving Strategies
（トークン消費を抑える方法）

## Related Skills
（関連スキルへのリンクテーブル）
```

## 現在の進捗

- [x] Phase 1: uverify 実装済み
- [x] Phase 1: udebug 実装済み
- [x] Phase 1: uui 実装済み
- [x] Phase 2: uscene
- [x] Phase 2: unity-cli に component modify, gameobject active 追加
- [x] Phase 3: uasset
- [x] Phase 3: unity-csharp
- [x] Phase 3: unity-cli に package コマンド追加
- [x] Phase 4: ubuild, uperf + build/profiler コマンド
