---
name: uscene
description: |
  Unityシーン構築・管理ワークフロー。オブジェクト配置→コンポーネント設定→Transform調整→Prefab化→シーン保存を一連で実行する。
  Use for: "シーンに配置して", "オブジェクト作って", "Prefab化して", "コンポーネント設定して", "シーン構築"
user-invocable: true
---

# Unity Scene Construction Workflow

シーン上のオブジェクト配置・設定・Prefab化を一連で行うワークフロー。

## CLI Setup

```bash
# グローバルインストール済みの場合
u <command>

# uvx 経由（インストール不要）
uvx --from git+https://github.com/bigdra50/unity-cli u <command>
```

以下のワークフロー内では `u` コマンドを使用する。

## Scene Construction Flow

```
Request
  │
  ▼
┌──────────────────────────────┐
│ Step 1: Survey               │
│ u scene active               │
│ u scene hierarchy -d 2       │
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│ Step 2: Create Objects       │
│ u gameobject create ...      │
│ u gameobject modify ...      │
│ u gameobject active ...      │
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│ Step 3: Configure Components │
│ u component add ...          │
│ u component modify ...       │
│ u component inspect ...      │
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│ Step 4: Prefab (optional)    │
│ u asset prefab ...           │
└──────────┬───────────────────┘
           ▼
┌──────────────────────────────┐
│ Step 5: Save Scene           │
│ u scene save                 │
└──────────┬───────────────────┘
           ▼
      Report
```

## Step Details

### Step 1: Survey

現在のシーン状態を把握する。

```bash
u scene active                    # シーン名・パス確認
u scene hierarchy -d 2            # 上位2階層の構造確認
```

階層が大きい場合はページネーションを使う:

```bash
u scene hierarchy -d 1 --page-size 20 --cursor 0
```

特定オブジェクトの詳細:

```bash
u gameobject find -n "Main Camera"
u component list -t "Main Camera"
```

### Step 2: Create & Arrange Objects

```bash
# 空のGameObject
u gameobject create -n "Enemy"

# プリミティブ付き
u gameobject create -n "Floor" -p Plane --position 0 0 0 --scale 10 1 10

# Transform変更
u gameobject modify -n "Enemy" --position 5 1 0 --rotation 0 45 0

# Active切り替え
u gameobject active -n "DebugUI" --no-active
u gameobject active -n "DebugUI" --active
```

### Step 3: Configure Components

```bash
# コンポーネント追加
u component add -t "Enemy" -T Rigidbody
u component add -t "Enemy" -T BoxCollider

# プロパティ変更
u component modify -t "Main Camera" -T Camera --prop fieldOfView --value 90
u component modify -t "Enemy" -T Rigidbody --prop mass --value 2.5
u component modify -t "Light" -T Light --prop m_Color --value '{"r":1,"g":0.9,"b":0.8,"a":1}'

# 変更確認
u component inspect -t "Main Camera" -T Camera
```

対応プロパティ型: int, float, bool, string, Enum, Vector2, Vector3, Color, ObjectReference

Enum は名前（文字列）またはインデックス（整数）で指定可能。

### Step 4: Prefab (optional)

構成済みオブジェクトをPrefab化:

```bash
u asset prefab -s "Enemy" -p "Assets/Prefabs/Enemy.prefab"
```

### Step 5: Save Scene

```bash
u scene save
# 別名保存
u scene save -p "Assets/Scenes/Level2.unity"
```

## Decision Criteria

| 状況 | 操作 |
|------|------|
| 新規オブジェクト配置 | `gameobject create` → `component add` → `component modify` |
| 既存オブジェクトの調整 | `gameobject find` → `gameobject modify` / `component modify` |
| オブジェクトの一時無効化 | `gameobject active --no-active` |
| 再利用したい構成 | `asset prefab` でPrefab化 |
| プロパティ名が不明 | `component inspect` で現在値とプロパティ名を確認 |
| SerializedProperty名が不明 | Unity Inspector のプロパティ名をそのまま使う（例: `fieldOfView`, `mass`）。内部名は `m_` プレフィックス付き（例: `m_LocalPosition`） |

## Command Reference

```bash
# Scene
u scene active                              # アクティブシーン情報
u scene hierarchy [-d DEPTH]                # 階層表示
u scene save [-p PATH]                      # シーン保存
u scene load --path PATH                    # シーン読み込み

# GameObject
u gameobject find -n NAME                   # 検索
u gameobject create -n NAME [-p PRIMITIVE]  # 作成
u gameobject modify -n NAME [--position X Y Z] [--rotation X Y Z] [--scale X Y Z]
u gameobject active -n NAME --active/--no-active
u gameobject delete -n NAME                 # 削除

# Component
u component list -t TARGET                  # 一覧
u component inspect -t TARGET -T TYPE       # 詳細
u component add -t TARGET -T TYPE           # 追加
u component remove -t TARGET -T TYPE        # 削除
u component modify -t TARGET -T TYPE --prop NAME --value VALUE

# Asset
u asset prefab -s SOURCE -p PATH            # Prefab作成
u asset info PATH                           # アセット情報
```

## Anti-Patterns

| NG | 理由 | 対策 |
|----|------|------|
| inspect せずに modify | プロパティ名の誤りに気付けない | 先に inspect で確認 |
| 大量オブジェクトを1つずつ create | 効率が悪い、スクリプトで生成すべき | 5個以上は C# スクリプトを書く |
| save せずに作業終了 | シーン変更が失われる | 最後に必ず `scene save` |
| Prefab化せずに複製 | 変更の一括適用ができない | 再利用する構成は Prefab化 |
| active で非表示にしたまま忘れる | ランタイムで見つからない | 作業後に active 状態を確認 |

## Token-Saving Strategies

| 状況 | 対応 |
|------|------|
| 階層が大きい | `-d 1` で深さ制限、`--page-size` で分割 |
| component inspect の出力が大きい | 必要なプロパティ名だけメモして modify |
| 同種オブジェクトを複数作成 | パターンが決まったら C# スクリプト化を提案 |

## Related Skills

| スキル | 関係 |
|--------|------|
| uverify | シーン構築中に C# を編集した場合のビルド検証 |
| udebug | シーン実行時のランタイムエラー調査 |
| uui | UI Toolkit 要素の配置・検査 |
