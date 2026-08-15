# Installation Guide

alred の通常利用、Python package、開発環境、エアギャップ環境への導入方法を説明します。
配布 binary の作成手順は利用者向け導入とは分離し、[BUILD.md](../../BUILD.md)を正本とします。

## 1. 推奨: GitHub Release binary

Linux x86_64 では、互換範囲の広い `glibc 2.17` binary を標準 artifact とします。通常は Python の
追加セットアップを必要としません。

```bash
curl -fL -O \
  https://github.com/suzuyu/alred/releases/latest/download/alred-linux-x86_64-glibc217
curl -fL -O \
  https://github.com/suzuyu/alred/releases/latest/download/alred-linux-x86_64-glibc217.sha256
sha256sum -c alred-linux-x86_64-glibc217.sha256
mkdir -p "$HOME/.local/bin"
install -m 0755 alred-linux-x86_64-glibc217 "$HOME/.local/bin/alred"
```

`$HOME/.local/bin` が `PATH` にない場合は shell の設定へ追加します。

```bash
export PATH="$HOME/.local/bin:$PATH"
alred --version
alred --help
```

特定 version を固定する場合は、URL の `latest/download` を `download/<tag>` に置き換えます。

```text
https://github.com/suzuyu/alred/releases/download/<tag>/alred-linux-x86_64-glibc217
```

追加の `glibc 2.28`／`glibc 2.34` variant は、その Release に明示的に添付されている場合だけ選択します。
迷う場合は `glibc 2.17` を使用してください。

| artifact | 想定する最小 glibc | OS の例 |
|---|---:|---|
| `alred-linux-x86_64-glibc217` | 2.17 | RHEL 7／8／9、Rocky Linux 8／9、AlmaLinux 8／9 |
| `alred-linux-x86_64-glibc228` | 2.28 | RHEL 8／9、Rocky Linux 8／9、AlmaLinux 8／9 |
| `alred-linux-x86_64-glibc234` | 2.34 | RHEL 9、Rocky Linux 9、AlmaLinux 9 |

実際の配布 artifact と検証済み環境は、対象 version の
[Release Notes](../releases/README.md)を確認してください。

## 2. エアギャップ環境へ持ち込む

ネットワーク接続可能な環境で、binary と同名の checksum file を取得します。持ち込み前と持ち込み後の
両方で checksum を検証し、binary と checksum を同じ組として管理してください。

```bash
sha256sum -c alred-linux-x86_64-glibc217.sha256
```

alred が生成する Evidence Package は別のデータ artifact です。実行 binary と Evidence Package を混同せず、
それぞれの checksum／Manifest を検証してください。

## 3. Python package として導入

Python 3.11 以上が必要です。GitHub から直接導入する例:

```bash
python -m pip install "git+https://github.com/suzuyu/alred.git"
alred --version
alred --help
```

version または tag を固定する場合:

```bash
python -m pip install "git+https://github.com/suzuyu/alred.git@<tag>"
```

## 4. 開発・検証環境

リポジトリを checkout し、lock file に固定された依存関係を `uv` で準備します。

```bash
git clone https://github.com/suzuyu/alred.git
cd alred
uv sync --frozen
uv run --frozen python alred.py --version
uv run --frozen python alred.py --help
```

開発規則と test は [CONTRIBUTING.md](../../CONTRIBUTING.md)、配布 binary の作成は
[BUILD.md](../../BUILD.md)を参照してください。

## 5. Shell completion

Bash の現在の shell で有効化する例:

```bash
source <(alred completion bash)
```

Zsh の現在の shell で有効化する例:

```zsh
source <(alred completion zsh)
```

永続化する場合は、使用する shell の起動 file へ同じ行を追加してください。

## 6. 導入後の確認

最初に version と top-level help が表示されることを確認します。

```bash
alred --version
alred --help
```

利用目的に応じた次の操作は [User Manuals](./README.md)から開始してください。機器接続を伴う command は、
対象 inventory と credential を確認するまで実行しないでください。
