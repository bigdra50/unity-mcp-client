# Unity MCP Client

Unity Editor を外部から制御するCLIツール。

## 概要

[CoplayDev/unity-mcp](https://github.com/CoplayDev/unity-mcp) サーバーと通信し、Unity Editorを操作します。

> Note: Unity Editor側で [unity-mcp](https://github.com/CoplayDev/unity-mcp) パッケージがインストールされ、MCPブリッジが起動している必要があります。

## 動作要件

- Python 3.8+
- [CoplayDev/unity-mcp](https://github.com/CoplayDev/unity-mcp) >= 8.1.0

## 制限事項

- TCP（レガシー）トランスポートのみ対応 - WebSocketトランスポートは未対応（次バージョンで実装予定）

## インストール

```bash
# uv でグローバルインストール（推奨）
uv tool install git+https://github.com/bigdra50/unity-mcp-client

# または uvx でインストールなしで実行
uvx --from git+https://github.com/bigdra50/unity-mcp-client unity-mcp state

# ローカルからインストール
git clone https://github.com/bigdra50/unity-mcp-client
cd unity-mcp-client
uv tool install .
```

## 使い方

```bash
# ヘルプ表示
unity-mcp --help

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

# ビルド検証（リフレッシュ→コンパイル待機→コンソール確認）
unity-mcp verify
```

## オプション

| オプション | 説明                              | デフォルト    |
| ---------- | --------------------------------- | ------------- |
| `--port`   | MCPサーバーポート                 | 6400          |
| `--host`   | MCPサーバーホスト                 | localhost     |
| `--count`  | 取得するログ件数                  | 20            |
| `--types`  | ログタイプ（error, warning, log） | error warning |

```bash
# 例: ポート6401でエラーのみ50件取得
unity-mcp console --port 6401 --types error --count 50
```

## トラブルシューティング

```bash
# Unity MCPサーバーが起動しているか確認
lsof -i :6400
```

## ライセンス

MIT License

## 関連リソース

- [CoplayDev/unity-mcp](https://github.com/CoplayDev/unity-mcp) - Unity Editor側のMCPサーバー実装
