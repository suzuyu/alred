# Link Normalization

## 1. 基本実行

import 済みの最新 Evidence Package を使用する場合は、source option を省略できる。

```bash
alred normalize-links
```

この command は `imported-evidence/latest` を検証して使用する。既存 file を直接使用する場合は、次のように
`--hosts` または `--input` を明示する。

```bash
alred normalize-links \
  --hosts hosts.yaml \
  --input raw \
  --output-confirmed output/links_confirmed.csv \
  --output-candidates output/links_candidates.csv \
  --output-dir output
```

実行directoryに`description_rules.yaml`が存在する場合、`--description-rules`を省略しても既定で使用する。
別fileを固定したい場合は明示する。
rule は定義順に評価し、最初に match した rule を使用する。同じ rule が 1 つの description から複数 endpoint を抽出した場合は
`DESCRIPTION_AMBIGUOUS` とし、link を自動生成しない。

## 2. Evidenceの扱い

| evidence | 出力 | confidence |
|---|---|---|
| 双方向LLDP | confirmed | `high` |
| LLDPと反対向きdescription | confirmed | `medium` |
| 双方向description | confirmed | `low` |
| 片方向LLDP | candidate | `low` |
| 片方向description | candidate | `low` |

LLDP は物理接続の優先 evidence であり、0 件でも description record は破棄されない。LLDP と description が同じ local interface で
異なる対向を示す場合、片方を消さず link diagnostic として残す。

正規化時は CSV に加えて次を生成する。

| 生成物 | 内容 |
|---|---|
| `link-diagnostics.yaml` | schema 検証可能な diagnostic、coverage、未評価 claim、影響 device、未解決 peer reference |
| `mismatch-links.md` | Summary、Affected Devices、mismatch、warning、unknown、未解決 peer reference。未評価 claim は Summary の件数だけを表示 |

双方向 LLDP と description の不整合は confirmed link に `CONFLICT` として関連付ける。description だけが示す非相互な接続は、
両端の running config を正常収集済みの場合だけ conflict とし、confirmed link へ昇格させず有向 claim として保持する。
片方向 LLDP も両端に LLDP link record がある場合だけ `ONE_WAY_LLDP` warning とする。server 収容、外部接続、対向未収集、
対向 source はあるが link record が 0 件の場合は mismatch にせず、`link-diagnostics.yaml` の `unevaluated_claims` へ理由付きで記録する。
`mismatch-links.md` は Summary に件数だけを表示し、endpoint／reason の詳細表は出力しない。inventory 外の名前も hostname typo の
確認対象として `link-diagnostics.yaml` には残すが、構成図へ `UNKNOWN` style は付与しない。

## 3. SVI description

既定では`interface Vlan*`のdescriptionを結線解析から除外する。SVIも対象にする場合だけ指定する。

```bash
alred normalize-links \
  --hosts hosts.yaml \
  --input raw \
  --include-svi \
  --output-confirmed output/links_confirmed.csv \
  --output-candidates output/links_candidates.csv
```

## 4. 確認手順

1. confirmed と candidate の件数を確認する。
2. `mismatch-links.md` の evaluation status と Summary を確認する。
3. Affected Devices の site、role、conflict link 数、local conflict 数、peer-reference 数、diagnostic code を確認する。
4. candidate、赤い claim、`link-diagnostics.yaml` の `unevaluated_claims` にある対向 hostname／interface と coverage を照合する。
5. conflict がある local interface は LLDP と description の両方を確認する。
6. mapping 適用後の hostname／interface が inventory の表記と一致することを確認する。
7. rule 変更後は同一 raw から再生成し、CSV、`link-diagnostics.yaml`、`mismatch-links.md` の差分を確認する。

CSV と diagnostic は決定的に sort し、処理完了後に atomic に置換する。入力 CSV header validation は未実装である。

## 5. Operation、Evidence Package、external import

商用環境の最新の正常公開済み current before を直接使用する。

```bash
alred normalize-links --latest-operation
```

特定 Operation は `--change-id <operation-id>` で固定する。隔離 lab の Evidence Package では次の 1 option で
Manifest-pinned inventory、config、任意 LLDP、rules を解決し、packaged canonical と照合する。

```bash
alred normalize-links \
  --evidence-package imported-evidence/<package-id>
```

外部 config import は `--running-config-import imported-running-config` を使用する。これらの source selector は
`--input` と排他である。alred 非依存データの import から構成図生成までの手順は
[External Data to Topology](05_EXTERNAL_DATA_TO_TOPOLOGY.md) を参照する。
