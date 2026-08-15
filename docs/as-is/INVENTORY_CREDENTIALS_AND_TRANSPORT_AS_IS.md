# Inventory, Credentials, and Transport As-Is

- Status: Reviewed
- Last reviewed: 2026-08-09
- Scope: `alred/inventory.py`、`alred/utils.py`、`alred/collect.py`、接続系CLI

## Evidence

| 種別 | pathまたはcommand | 確認内容 |
|---|---|---|
| Code | `alred/inventory.py` | `hosts.txt`解析、inventory生成・正規化 |
| Code | `alred/utils.py` | credential、Netmiko driver、SSH option解決 |
| Code | `alred/collect.py` | SSH、NX-API、auto transport、接続確認 |
| Code | `alred/constants.py` | device type、driver、command、session準備 |
| Code | `alred/cli.py` | inventory探索、target・policy filter、並列接続確認 |
| User doc | `CONFIG.md` | inventoryとcredential入力 |
| Test | `tests/test_phase0_collect_baseline.py`、接続をmockする各test | offlineの入力・出力境界 |

## Observed behavior

### Inventory

- `hosts.txt`の有効行は`<IP> <hostname> # <device_type>[, metadata...]`である。
- 空行と行頭`#`を無視し、同一file内のIPまたはhostname重複を拒否する。
- device type省略時は`unknown`で、metadataは`key=value`を基本とする。一部の既知keyは
  `key:value`も受け付ける。
- `prepare-hosts`は`all.hosts.<hostname>`を持つAnsible風YAMLを生成し、既知device typeでは
  AnsibleおよびNetmiko属性を補う。
- inventory loaderは`ansible_host`を正規化後の`ip`とし、未知fieldはhost listへ保持しない。
- 明示的なtarget hostname filterの後、policyのinclude、excludeの順で対象を選択する。

### Credentials

- 必須credentialの解決順は、CLI、credential YAMLのhost／device type／defaults、
  ASA/ASAv専用環境変数、共通`ALRED_*`、legacy `NW_TOOL_*`である。
- credential YAMLは`credentials` wrapperを省略でき、literalまたは`*_env`参照を使える。
- `--credentials`省略時でも、そのoptionを持つcommandでは`./clab_credentials.yaml`を探索する。
- usernameとpasswordの片方だけが解決された場合は拒否する。enable secretは空を許可する。
- optional credential解決はlab config変換で使用し、username／passwordが両方未設定なら`None`を
  返す。これはASA/ASAv専用環境変数を参照しない。

### Transport

- `ssh`はNetmikoを使用し、inventoryのdriverまたはdevice type overrideで接続する。
- SR Linuxは`terminal_server` driverとsession準備commandを使う。
- ASA／ASAv／EOSはprivileged execへ入り、ASA／ASAvではenable secretを必須とする。
- NX-APIはNX-OSだけを対象とし、JSONを試してからtextへfallbackする。scheme未指定時はHTTPS、
  HTTPの順で試す。
- `auto`はNX-OSでNX-APIを優先し、command単位の失敗時にSSHへfallbackする。それ以外の
  device typeではSSHを使用する。
- NX-API TLS certificate検証は`ALRED_NXAPI_VERIFY_SSL`がtruthyの場合だけ有効で、既定は無効である。
- 接続確認はTCP probeと認証／enable確認を分け、hostごとにstage、resolved transport、経過時間、
  errorを返す。

## Documented but not verified

- `CONFIG.md`に列挙された全device typeについて、現行release・実機でのdriver動作は今回確認していない。
- NX-APIのHTTP fallbackとTLS検証無効の運用上の意図は文書化されていない。

## Inferred behavior

- inventory YAMLはAnsible互換を意識しているが、alredが読み取るfieldは限定されるため、任意の
  Ansible inventory互換を保証するものではない。
- `auto`は可用性を優先するlegacy動作であり、transport固定と証跡固定が必要なoperationでは
  execution contextを別途保存する必要がある。

## Unknowns and conflicts

- inventory top-level schema、hostname／IPの型・形式、未知field、空値に対する共通validationはない。
- credential YAMLのpermission検査、secret file検査、symbolic link policyは実装されていない。
- NX-API TLS検証無効の既定値を将来維持するかは、安全性と後方互換性を含む設計判断が必要である。
- device typeごとの接続・収集capabilityを示す共通registryはなく、NX-OS Overlay用Registryとは
  責務が異なる。

## Recommended design disposition

- 現行inventoryとcredentialの入力互換性を維持し、正規化後のcanonical host fieldを共通設計へ
  固定する。
- credential値はoperation artifact、log、fixtureへ保存せず、使用した非秘密contextだけをhashで
  追跡する。
- `auto` fallbackはlegacy collectionで維持し、managed operationではresolved transportを記録する。
- TLS既定値の変更はこの整理作業では行わず、別の安全性判断として扱う。

## Integration

- Design document: [Inventory, Credentials, and Device Access Design](../design/common/INVENTORY_CREDENTIALS_AND_DEVICE_ACCESS_DESIGN.md)
- ADR: TLS policyを変更する場合は必要
- Integrated date: 2026-08-09
