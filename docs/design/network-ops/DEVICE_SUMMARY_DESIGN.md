# Device Summary Design

## 1. 目的と範囲

Health Check の同一 Collection attempt で得た inventory、show command、role 解決、Health Result から、
機器一覧を 1 device 1 row の Markdown と CSV で生成する。初期実装は NX-OS を対象とするが、列名と
canonical row は vendor 固有名を避け、将来の他 OS adapter を追加できる形とする。

初期範囲に vPC peer、冗長構成の推定、Smart Licensing の registration／authorization／compliance 判定は
含めない。既存の `vpc_health` は変更せず、Device Summary から参照しない。

## 2. 成果物と生成時点

phase ごとの Health 評価完了後に次を生成する。

```text
operations/<change-id>/health/<phase>/device-summary.md
operations/<change-id>/health/<phase>/device-summary.csv
```

before／rollback の immutable attempt を使用する場合は attempt directory に先に生成し、attempt 完了後だけ
既存の publish 処理で canonical phase directory へコピーする。失敗 attempt から canonical 成果物を更新しない。

Markdown と CSV は同じ canonical row と列順から生成する。row は site の `priority`、site 名、解決済み
topology role の `priority`、topology role 名、hostname の順で生成する。数値が小さいほど先に表示する。
site または role が未解決、競合、または固定 artifact に `priority` がない場合は `99` とする。CSV は UTF-8、
header あり、LF 改行とし、Python `csv` の標準 quoting を使用する。複数値は semicolon と space の `; ` で連結する。

## 3. 列と取得元

列順は次で固定する。

| 列 | canonical source | 欠落時 |
|---|---|---|
| `hostname` | Snapshot の host key。元は canonical inventory | 生成対象外 |
| `management_ip` | `hosts.<host>.address` | `UNKNOWN` |
| `manufacturer` | platform mapping。初期 NX-OS は `Cisco` | `UNKNOWN` |
| `model` | `common.system.model`。`show version` | `UNKNOWN` |
| `serial_number` | `common.inventory.components` の primary chassis | `UNKNOWN` |
| `os_type` | `hosts.<host>.platform` | `unknown` |
| `os_version` | `common.system.version`。`show version` | `UNKNOWN` |
| `license_usage` | `common.license.usage` | `UNKNOWN` または `NOT_APPLICABLE` |
| `license_parse_status` | `sources.license_usage.parse_status` と applicability | 下記の状態値 |
| `site` | inventory の `site`／`metadata.site`、次に固定済み `sites.yaml` の hostname rule | `UNKNOWN` |
| `topology_role` | `ResolvedRoles.spec.devices.<host>.topology_role` | `UNKNOWN` |
| `functions` | 同 device の function 名を辞書順で列挙 | `-` |
| `health_result` | Health Result の host 別 check を共通 severity 順で集約 | `NOT_APPLICABLE` |
| `collection_status` | `hosts.<host>.collection_status` | `UNKNOWN` |
| `collected_at` | `Snapshot.created_at` の wall-clock 部分。UTC offset は表示しない | `UNKNOWN` |

host 別 `health_result` の優先順位は `PLAN_ERROR`、`FAIL`、`UNKNOWN`、`WARN`、`PASS`、
`NOT_APPLICABLE` とし、全体結果を各 host へ複製しない。profile scope 外の記録がある場合は、その host の
`unexecuted_hosts.profile_result` も同じ優先順位で集約する。

`collected_at` は Markdown／CSV の視認性を優先し、`2026-08-19T00:03:48+09:00` を
`2026-08-19T00:03:48` と表示する。時刻の変換は行わず、UTC offset を除いた wall-clock 部分を使用する。timezone を
含む正本の timestamp は Snapshot の `created_at` と `timezone` に保持する。

`functions` は role policy で解決した function 名であり、設定済みであることを名前だけから保証しない。
期待状態と設定 evidence の詳細は `resolved-roles.yaml` と Checklist を参照する。

並び順に使用する role の `priority` は `roles.yaml` の topology role rule から `ResolvedRoles` の device ごとに
固定する。site の `priority` は固定した `sites.yaml` から取得する。値自体は Device Summary の列へ重複出力せず、
`resolved-roles.yaml` と execution context に固定した `sites.yaml` から追跡する。数値が小さいほど先に表示する意味は
topology renderer の site／role priority と共通とする。

`site` は inventory の明示値を優先し、空または未定義の場合だけ `sites.yaml` の `site_detection` rule で
hostname を解決する。`health-check before` は明示した `--sites`、または存在する `./sites.yaml` の絶対 path と
SHA-256 を execution context に固定し、after／rollback は同じ source を hash 検証して再利用する。固定 source が
ない旧 Operation や rule 不一致では、現在の作業 directory の `sites.yaml` を暗黙に追加せず `UNKNOWN` とする。

## 4. NX-OS command と parser

| command ID | command | 収集 | parser backend | canonical output |
|---|---|---|---|---|
| `show_version` | `show version` | required | alred native | `common.system` |
| `inventory` | `show inventory` | optional | NTC Templates | `common.inventory.components` |
| `license_usage` | `show license usage` | optional | alred adapter。表形式は NTC Templates、feature block 形式は native parser | `common.license` |

`show license all` は初期 Device Summary では収集しない。Smart Licensing 全体状態を扱う場合は、対象 model／
release、command、状態判定を別途設計する。

collector は parser を実行せず raw output を Collection Manifest に固定する。Snapshot builder が raw output を
読み、出力形式を判定する alred adapter から、固定した package resource の NTC template または native parser で
解析する。Netmiko の `use_textfsm=True` は使用しないため、SSH／NX-API／transcript import の各入力で同じ解析経路を
使用できる。

alred native parser、NTC Templates、TextFSM の version と、template file 名、template SHA-256 を Snapshot の
`parser_versions` と source provenance へ記録する。`license_usage` source の parser は format 判定を所有する
`nxos.license_usage` とし、表形式で使用する NTC template も provenance へ併記する。`NTC_TEMPLATES_DIR` などの
実行環境 override で template を暗黙に差し替えない。

## 5. `show inventory` の解析と primary chassis

NTC Templates の `cisco_nxos_show_inventory.textfsm` が出力する `NAME`、`DESCR`、`PID`、`VID`、`SN` を
次へ正規化する。

```json
{
  "inventory": {
    "components": [
      {
        "name": "Chassis",
        "description": "Nexus9000 C93180YC-EX Chassis",
        "product_id": "N9K-C93180YC-EX",
        "version_id": "V01",
        "serial_number": "SAL00000001"
      }
    ]
  }
}
```

primary chassis は次の順で選ぶ。

1. `name` が大文字・小文字を区別せず `Chassis` の component
2. 1 がなければ `product_id` と `common.system.model` が大文字・小文字を除いて一致する component
3. 候補の非空 serial number が一意なら採用
4. 候補がない、または異なる serial number が複数なら推測せず `UNKNOWN`

module、fan、power supply、transceiver の serial number を chassis serial として代用しない。

空 output、CLI error、`NAME`／`PID` anchor 欠落、row 0 件、NTC parse error は parser error とする。

## 6. `show license usage` の解析

表形式では `cisco_nxos_show_license_usage.textfsm` が出力する `FEATURE`、`INSTALLED`、`LICENSE_COUNT`、
`STATUS`、`EXPIRY_DATE`、`COMMENTS` を次へ正規化する。NX-OS が次の feature block 形式を返す場合は、alred の
native parser で同じ canonical data へ正規化する。

```text
License Authorization:
  Status: Not Applicable

(LAN_ENTERPRISE_SERVICES_PKG):
  Description: LAN license
  Count: 1
  Version: 1.0
  Status: IN USE
  Enforcement Type: NOT ENFORCED
  License Type: Generic
```

```json
{
  "license": {
    "applicable": true,
    "usage": [
      {
        "feature": "LAN_ENTERPRISE_SERVICES_PKG",
        "installed": true,
        "license_count": null,
        "usage_status": "in_use",
        "expiry_date": null,
        "comments": null
      }
    ]
  }
}
```

- `Yes`／`No` は boolean へ変換する。
- license count の `-` は `null`、数値は integer とする。
- `In use`／`Unused` は `in_use`／`unused` とする。
- 空の expiry date と comments は `null` とする。
- feature は辞書順で表示し、同名 feature が複数 row に現れた場合は曖昧なため parser error とする。
- feature block 形式では block の存在を `installed: true` とし、`Count` と `Status` を必須とする。既知 field の
  重複、未知の非空行、非整数の `Count`、`IN USE`／`UNUSED` 以外の `Status` は parser error とする。
- feature block 形式には expiry date と comments がないため `null` とする。`Description` を comments へ転用しない。
- `License Authorization` の `Status: Not Applicable` は authorization の状態であり、feature block が存在する場合は
  usage 自体を `not_applicable` にしない。feature block がない同 header だけの出力も、安全に判断できないため
  `unknown` とする。

`license_usage` 列には次の形式を semicolon 連結して表示する。

```text
LAN_ENTERPRISE_SERVICES_PKG(installed=yes,status=in_use,count=-,expiry=-)
```

これは観測した usage であり、契約、entitlement、registration、authorization、compliance の正常性を意味しない。
初期実装では license evaluator を追加せず、既存 Health Result を変更しない。

`license_parse_status` は次とする。

| 状態 | 条件 |
|---|---|
| `parsed` | command 取得と row 解析に成功 |
| `not_applicable` | 対応済みの明示的な「license 対象なし」出力を解析 |
| `not_collected` | source がない |
| `unsupported` | command ID に対応する parser がない |
| `unknown` | collection 失敗、空、未知形式、parser error |

header だけで row がない入力を `not_applicable` と推測せず `unknown` とする。

## 7. Error、evidence、security

inventory または license の取得・解析失敗だけで Device Summary 全体を生成不能にしない。対象 device の row を
残し、該当値と parse status で不明を示す。raw output、command、transport、取得時刻、hash、parser、template を
Snapshot source から追跡可能にする。

実機 fixture は hostname、管理 IP、serial number を sanitization してから保存する。Device Summary と Snapshot は
serial number を含む運用成果物であるため、repository へ commit せず、外部共有時は Support Bundle の policy と
組織の情報管理規則を適用する。

## 8. Dependency、配布、検証

alred が NTC Templates API を直接使用するため、`ntc-templates` を直接 runtime dependency として宣言し、
major version を上限付きで管理する。PyInstaller binary には `ntc_templates` の template data と、
`ntc_templates`／`textfsm` の distribution metadata を同梱する。
NTC Templates と TextFSM の Apache-2.0 notice は第三者ライセンス一覧へ含める。

test は少なくとも次を含む。

- NX-OS 9.x／10.x 相当の sanitized inventory／license output
- chassis と module／power supply が混在する inventory
- command error、空 output、anchor 欠落、row 0 件、未知 row、重複 feature
- collection／parse failure でも他 device の row を維持すること
- Markdown escaping、CSV quoting、複数値、site priority／role priority／hostname sort、inventory site 優先と `sites.yaml` fallback
- source tree と PyInstaller における NTC template resource の存在
- parser backend、package version、template 名、template SHA-256 の provenance
