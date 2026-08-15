# Common Preparation

この章は、alredのhealth checkを実行するすべてのシナリオに共通する事前準備です。
直接収集、取得済みrawログ、外部transcript、NX-OS Overlayのいずれを使用する場合も、
最初にこの章を確認してください。

各シナリオ文書には、共通準備を繰り返さず、そのシナリオ固有のprofile、入力、確認項目だけを
記載します。

## 1. 実行環境を確認

```bash
alred --version
alred health-check before --help
```

リポジトリをcheckoutした開発環境では、次のように実行できます。

```bash
uv run python alred.py --version
uv run python alred.py health-check before --help
```

確認項目:

- 利用予定のCLIとoptionがhelpに表示される
- 成果物を書き込める作業ディレクトリである
- 直接収集では対象機器へ到達でき、showコマンドを実行できる
- オフライン解析では入力ログを読み取れる
- 本番作業前にラボまたは取得済みログで出力形式を確認している

## 2. timezoneを確認

timezoneの既定値は`ALRED_TIMEZONE`、未設定の場合は`Asia/Tokyo`です。JSTで実施する場合の
設定例:

```env
ALRED_TIMEZONE=Asia/Tokyo
```

一時的に変更する場合はCLIで指定できます。

```bash
alred health-check before \
  --input ./raw-before \
  --input-format alred-collect \
  --timezone Asia/Tokyo
```

beforeで確定したtimezoneはoperationへ記録され、afterやrollbackでも同じ条件を使用します。
端末、Checklist、Snapshotの日時に`+09:00`が表示されることを確認してください。

## 3. 認証方法を決める

直接収集では、既存collect runnerの認証optionを使用します。

| 方法 | 主な指定 | 用途 |
|---|---|---|
| 対話入力 | `--ask-pass` | passwordをファイルやshell履歴へ残さない |
| credentials YAML | `--credentials FILE` | 既存の認証管理ファイルを利用 |
| 環境設定 | `ALRED_USERNAME`など | 管理された実行環境で利用 |
| CLI指定 | `--username`、`--password` | 一時試験。shell履歴に注意 |

passwordとenable secretはoperation成果物へ保存しません。profile、rawログ、running configには
環境固有情報が含まれるため、成果物の権限と共有先を確認してください。

オフライン解析だけを行う場合、機器認証情報は不要です。

### 3.1 health-checkのtransport

`health-check before/after/rollback`で機器へ直接接続する場合、transportの既定値は`ssh`です。
`show logging`を含むNX-OS CLI出力を一貫して取得し、NX-APIとSSHの二重収集による時間増加を
避けるため、通常は`--transport`を指定する必要はありません。

```bash
alred health-check before \
  --collect \
  --hosts ./hosts.lab.yaml \
  --ask-pass
```

`--transport auto`または`--transport nxapi`は明示指定できますが、profileが要求するコマンドを
取得できない場合は`UNKNOWN`などの収集不足判定になります。afterはbeforeのexecution contextに
保存されたtransportを継承します。変更前に作成されたoperationで`auto`が記録されている場合も、
そのoperationのafterでは記録済み`auto`を継承します。

## 4. 配布サンプルを生成

profileやshow commandの例を確認する場合:

```bash
alred generate-sample-config --output-dir ./samples
```

既存ファイルは既定で上書きしません。更新されたtemplateを意図的に反映する場合だけ、
内容を退避・比較したうえで`--force`を使用します。

主なhealth check関連サンプル:

```text
samples/
├── health-check-profile.logging-excludes.example.yaml
├── health-check-profile.network-baseline-logging-3days.example.yaml
└── show_commands.example.txt
```

独自profileを使用する場合は、サンプルを作業用ファイルへコピーし、元の配布サンプルは変更しない
運用を推奨します。

## 5. inventoryを準備

### 5.1 hosts.txt

`hosts.yaml`は、原則として`prepare-hosts`で生成します。

```text
192.0.2.11 leaf01 # nxos
192.0.2.12 leaf02 # nxos
192.0.2.21 spine01 # nxos
```

ドキュメント用アドレスのため、実際には対象環境の管理IPとhostnameへ置き換えます。

### 5.2 hosts.yamlを生成

```bash
alred prepare-hosts \
  --input ./hosts.txt \
  --output ./hosts.lab.yaml
```

生成後の例:

```yaml
all:
  hosts:
    leaf01:
      ansible_host: 192.0.2.11
      device_type: nxos
      ansible_network_os: cisco.nxos.nxos
      ansible_connection: network_cli
      netmiko_device_type: cisco_nxos
    leaf02:
      ansible_host: 192.0.2.12
      device_type: nxos
      ansible_network_os: cisco.nxos.nxos
      ansible_connection: network_cli
      netmiko_device_type: cisco_nxos
    spine01:
      ansible_host: 192.0.2.21
      device_type: nxos
      ansible_network_os: cisco.nxos.nxos
      ansible_connection: network_cli
      netmiko_device_type: cisco_nxos
```

既存inventoryを使用する場合も、実行前に内容を表示して対象を確認します。

```bash
sed -n '1,240p' ./hosts.lab.yaml
```

確認項目:

- hostnameと管理IPが正しい
- `device_type`が対象platformと一致する
- 重複hostnameや意図しない本番機が含まれていない
- 変更対象だけでなく、影響確認に必要なpeerやFabric機器が含まれている
- `--target-hosts`を使用する場合、除外される機器が意図どおりである

## 6. 入力方式を決める

| 方式 | 指定 | 機器アクセス |
|---|---|---|
| 直接収集 | `--collect --hosts ./hosts.lab.yaml` | あり。showコマンドのみ |
| alred rawログ | `--input DIR --input-format alred-collect` | なし |
| 外部transcript | `--input DIR --input-format nxos-transcript` | なし |

直接収集のhealth check自体はshowコマンドを実行し、設定投入を行いません。
Overlay変更管理のapplyなど、設定を変更する別コマンドとは区別してください。

外部transcriptでは、promptのhostnameと実行コマンドを一意に識別できる必要があります。
hostname aliasが必要な場合は`--hosts`でinventoryを指定します。

## 7. operation保存先を確認

既定では次へ保存されます。

```text
operations/live/YYYY/MM/DD/<change-id>/
```

書き込み先を変更する場合は`--operations-root`を使用します。

```bash
alred health-check before \
  --input ./raw-before \
  --input-format alred-collect \
  --operations-root ./operations
```

確認項目:

- 必要な空き容量がある
- 作業者以外へ不要な読み取り権限が付いていない
- beforeからafter、必要ならrollbackまで保持できる
- backupや共有の対象範囲が決まっている
- rawログやrunning configを外部共有する際のredaction手順がある

## 8. 共通の実施前Checklist

作業開始前に次を確認します。

- [ ] CLI versionと実行方法を確認した
- [ ] timezoneを確認した
- [ ] 認証方法を決め、secretの保存先を確認した
- [ ] inventoryのhostname、管理IP、対象台数を確認した
- [ ] 直接収集またはオフライン入力の方式を決めた
- [ ] 使用するprofileとlogging範囲を決めた
- [ ] operation保存先と権限を確認した
- [ ] ラボまたは取得済みログで出力イメージを確認した
- [ ] 対象外の本番機が含まれていない
- [ ] FAIL、UNKNOWN、WARN発生時の継続判断者を決めた

## 9. 次のシナリオを選択

共通準備の完了後、目的に応じて進みます。

- 基本的なbefore / after: [Quick Start](./01_QUICK_START.md)
- 入力方式、logging範囲、rollback: [Health Check Operations](./02_HEALTH_CHECK_OPERATIONS.md)
- 独自profile: [Profile Guide](./03_PROFILE_GUIDE.md)
- alred内でVNI設定投入:
  [Overlay ChangeSet作成ガイド](./07_OVERLAY_CHANGESET_GUIDE.md) →
  [alredによるVNI設定投入](./08_ALRED_OVERLAY_CHANGE_APPLY.md)
- EVPN/VXLANとVNI map: [NX-OS Overlay Health Check](./06_NXOS_OVERLAY_HEALTH_CHECK.md)
- 問題の切り分け: [Troubleshooting](./05_TROUBLESHOOTING.md)
