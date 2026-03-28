# chatgpt_gpts_sample

ChatGPT GPTs で、`config-all-<timestamp>.tar` を知識として使い、
次の 4 種類の出力や確認を安定して実施するためのサンプル一式です。

- リンク構成を CSV で生成
- 構成図を Mermaid で生成
- VNI の一覧表を Markdown 表で生成
- 不具合や構成上の懸念を確認して要約

## ファイル一覧

- `instructions.txt`
  - GPT Builder の `Instructions` に貼り付ける本文
- `network-output-rules.md`
  - Knowledge に追加する詳細ルール
- `network-output-examples.md`
  - Knowledge に追加する短い正解例
- `README.md`
  - この使い方説明

## ChatGPT GPTs への設定方法

1. ChatGPT で GPTs を開く
2. `Create` または既存 GPT の `Edit` を開く
3. `Configure` タブを開く
4. `Instructions` に `instructions.txt` の内容を貼り付ける
5. `Conversation starters` に以下を設定する

```text
リンク構成を CSV で生成して
構成図を作成して
VNI の一覧表を作成して
不具合がないか確認してください
```

6. `Knowledge` に以下をアップロードする
   - `config-all-<timestamp>.tar`
   - `network-output-rules.md`
   - `network-output-examples.md`
7. 必要なら複数の `config-all-*.tar` を追加する
8. 保存して動作確認する

## 前提

- アーカイブ名は `config-all-YYYYMMDD-HHMMSS.tar` を想定しています
- 複数の `config-all-*.tar` がある場合、Instructions では最新版を使う前提です
- `collect-all` という言葉は GPT に前提知識として求めません

## 補足

- `Instructions` は 8000 文字制限に収まるよう短くしています
- 詳細な判定や除外条件は `network-output-rules.md` に逃がしています
- 出力がぶれる場合は、`network-output-examples.md` に短い正解例を追加すると安定しやすいです
