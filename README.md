# Unity MCP Client

Unity Editor を外部から制御するCLIツール。

## 概要

[CoplayDev/unity-mcp](https://github.com/CoplayDev/unity-mcp) パッケージのTCPブリッジと直接通信し、Unity Editorを操作します。

MCPサーバー経由ではなく直接通信する理由:
- MCPツールを大量に読み込むと、コーディングエージェントのコンテキストウィンドウを常に圧迫する
- このCLIツールならBashツール経由で必要な時だけ呼び出せる

```
通常のMCPフロー:
  Claude → MCP Server → Unity TCP Bridge → Unity Editor
         (ツール定義がコンテキストを常に消費)

このツール:
  Claude → Bash → unity-mcp-client → Unity TCP Bridge → Unity Editor
                (必要な時だけ呼び出し)
```

> Note: Unity Editor側で [unity-mcp](https://github.com/CoplayDev/unity-mcp) パッケージがインストールされ、TCPブリッジが起動している必要があります（Window > MCP For Unity）。

## 主な機能

### シーン階層探索

#### デフォルト動作（サマリー）
大規模シーンでも安全に使えるよう、デフォルトはルートオブジェクトのみを返します。

```bash
# デフォルト: ルートオブジェクトのみ（子の数を含む）
unity-mcp scene hierarchy
# → 7 roots, 387 total objects

# 深さを指定して展開
unity-mcp scene hierarchy --depth 1   # ルート + 直下の子
unity-mcp scene hierarchy --depth 2   # 2階層まで

# 全階層を取得（大規模シーン注意）
unity-mcp scene hierarchy --full      # ネスト構造で全取得
unity-mcp scene hierarchy --iterate-all  # フラット化してページング取得
```

#### Python API
```python
from unity_mcp_client import UnityMCPClient

client = UnityMCPClient()

# サマリー取得（推奨）
result = client.scene.get_hierarchy_summary(depth=0)
print(f"Total: {result['data']['summary']['totalCount']} objects")
for item in result['data']['items']:
    print(f"- {item['name']} ({item['descendantCount']} descendants)")

# 全階層をイテレート（大規模シーン対応）
for page in client.scene.iterate_hierarchy(page_size=100):
    for item in page['data']['items']:
        print(f"- {item['name']} (depth: {item.get('_depth', 0)})")
```

#### 機能
- **安全なデフォルト**: ルートオブジェクトのみ返却、大規模シーンでも高速
- **段階的な詳細取得**: `--depth` で必要な深さまで展開
- **ページングサポート**: `--iterate-all` で全階層をメモリ効率よく取得
- **サーバーバージョン互換**: v8.6.0+とv8.3.0以前の両方に対応

## 動作要件

- [uvx](https://docs.astral.sh/uv/guides/tools/)
- Python 3.11+
- [CoplayDev/unity-mcp](https://github.com/CoplayDev/unity-mcp) >= 8.1.0

## 制限事項

- TCPブリッジ（Stdio Bridge）への直接接続のみ対応
- MCPプロトコル（stdio/SSE）は使用しません

## インストール

```bash
# uvx でインストールなしで実行（推奨）
uvx --from git+https://github.com/bigdra50/unity-mcp-client unity-mcp state

# グローバルインストールする場合
uv tool install git+https://github.com/bigdra50/unity-mcp-client
```

## 使い方

```bash
# ヘルプ表示
unity-mcp --help

# 現在の設定を確認
unity-mcp config

# エディタ状態確認
unity-mcp state

# コンソールログ取得
unity-mcp console
unity-mcp console --types error --count 10

# Play mode制御
unity-mcp play
unity-mcp stop

# アセットリフレッシュ
unity-mcp refresh

# GameObject検索
unity-mcp find "Main Camera"

# テスト実行
unity-mcp tests edit
unity-mcp tests play

# ビルド検証（リフレッシュ→クリア→コンパイル待機→コンソール確認）
unity-mcp verify
unity-mcp verify --timeout 120 --connection-timeout 60

# シーン操作
unity-mcp scene active          # アクティブシーン情報
unity-mcp scene hierarchy       # ルートオブジェクトのみ（サマリー）
unity-mcp scene hierarchy --depth 1   # ルート+直下の子まで
unity-mcp scene hierarchy --full      # 全階層（ネスト構造）
unity-mcp scene hierarchy --iterate-all --page-size 100  # 全階層（フラット化）
unity-mcp scene build-settings  # ビルド設定のシーン一覧
unity-mcp scene load --name MainScene
unity-mcp scene load --path Assets/Scenes/Level1.unity
unity-mcp scene save
unity-mcp scene create --name NewScene --path Assets/Scenes

# GameObject操作
unity-mcp gameobject find "Main Camera"
unity-mcp gameobject find "Player" --iterate-all --page-size 20  # ページング対応
unity-mcp gameobject create --name "MyCube" --primitive Cube --position 0,1,0
unity-mcp gameobject modify --name "MyCube" --position 5,0,0 --rotation 0,45,0
unity-mcp gameobject delete --name "MyCube"

# マテリアル操作
unity-mcp material info --path Assets/Materials/Default.mat
unity-mcp material create --path Assets/Materials/New.mat --shader Standard
unity-mcp material set-color --path Assets/Materials/New.mat --color 1,0,0,1
```

## 設定ファイル

`.unity-mcp.toml` をカレントディレクトリまたはUnityプロジェクトルートに配置することで、デフォルト値を設定できます。

```bash
# デフォルト設定ファイルを生成
unity-mcp config init

# 出力先を指定
unity-mcp config init --output my-config.toml

# 既存ファイルを上書き
unity-mcp config init --force
```

```toml
# .unity-mcp.toml

# 接続設定
port = 6401
host = "localhost"

# タイムアウト設定（秒）
timeout = 5.0              # 通常操作のTCPタイムアウト
connection_timeout = 30.0  # verifyコマンド用（重い処理向け）

# リトライ設定
retry = 3                  # verifyコマンドの接続リトライ回数

# コンソールログ設定
log_types = ["error", "warning"]
log_count = 20
```

### 設定の優先順位

1. CLIオプション（`--port`, `--timeout` など）
2. `.unity-mcp.toml`（カレントディレクトリ）
3. `.unity-mcp.toml`（Unityプロジェクトルート）
4. EditorPrefs（macOSのみ、ポート自動検出）
5. デフォルト値

## オプション

### 共通オプション

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `--port` | MCPサーバーポート | 設定ファイル or 6400 |
| `--host` | MCPサーバーホスト | localhost |
| `--count` | 取得するログ件数 | 20 |
| `--types` | ログタイプ（error, warning, log） | error warning |

### verify専用オプション

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `--timeout` | コンパイル待機の最大秒数 | 60 |
| `--connection-timeout` | TCP接続タイムアウト（秒） | 30.0 |
| `--retry` | 接続失敗時のリトライ回数 | 3 |

### scene専用オプション

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `--name` | シーン名（create/load） | - |
| `--path` | シーンパス（create/load/save） | - |
| `--build-index` | ビルドインデックス（load） | - |
| `--depth` | 階層の深さ（0=ルートのみ, 1=直下の子まで等） | 0 |
| `--full` | 全階層をネスト構造で取得 | false |
| `--page-size` | 1ページあたりのアイテム数（--iterate-all時）※1 | 50 |
| `--cursor` | 開始カーソル位置（--full時）※1 | 0 |
| `--max-nodes` | 取得ノード総数の上限（--full時）※1 | 1000 |
| `--max-children-per-node` | ノードあたりの子要素上限（--full時）※1 | 200 |
| `--include-transform` | Transform情報を含める（hierarchy） | false |
| `--iterate-all` | 全ページを自動取得（hierarchy, find） | false |

※1 ページングオプションはサーバーv8.6.0+で有効。v8.3.0以前ではデフォルト動作（全階層取得）のみ。`--iterate-all` は両バージョンで動作。

### gameobject専用オプション

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `--name` | オブジェクト名 | - |
| `--primitive` | プリミティブ (Cube, Sphere, Capsule, Cylinder, Plane, Quad) | - |
| `--position` | 位置 (x,y,z) | - |
| `--rotation` | 回転 (x,y,z) | - |
| `--scale` | スケール (x,y,z) | - |
| `--parent` | 親オブジェクト名 | - |

### material専用オプション

| オプション | 説明 | デフォルト |
|-----------|------|-----------|
| `--path` | マテリアルパス | - |
| `--shader` | シェーダー名 | Standard |
| `--color` | 色 (r,g,b,a) | - |
| `--property` | プロパティ名 | - |
| `--value` | プロパティ値 | - |

```bash
# 例: ポート6401でエラーのみ50件取得
unity-mcp console --port 6401 --types error --count 50

# 例: 大規模プロジェクト向けverify（タイムアウト120秒、接続タイムアウト60秒）
unity-mcp verify --timeout 120 --connection-timeout 60
```

## ポート自動検出

ポートは以下の順序で検出されます：

1. `.unity-mcp.toml` の `port` 設定
2. macOS: Unity EditorPrefsから自動検出
3. デフォルト: 6400

```bash
# 自動検出されたポートを使用
unity-mcp state

# 手動指定（自動検出より優先）
unity-mcp --port 6401 state
```

## トラブルシューティング

```bash
# Unity MCPサーバーが起動しているか確認
lsof -i :6400

# 現在の設定を確認
unity-mcp config
```

## ライセンス

MIT License

## 関連リソース

- [CoplayDev/unity-mcp](https://github.com/CoplayDev/unity-mcp) - Unity Editor側のMCPサーバー実装
