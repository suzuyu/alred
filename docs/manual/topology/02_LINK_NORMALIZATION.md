# Link Normalization

## 1. 基本実行

```bash
alred normalize-links \
  --hosts hosts.yaml \
  --input raw \
  --output-confirmed output/links_confirmed.csv \
  --output-candidates output/links_candidates.csv
```

実行directoryに`description_rules.yaml`が存在する場合、`--description-rules`を省略しても既定で使用する。
別fileを固定したい場合は明示する。

## 2. Evidenceの扱い

| evidence | 出力 | confidence |
|---|---|---|
| 双方向LLDP | confirmed | `high` |
| LLDPと反対向きdescription | confirmed | `medium` |
| 双方向description | confirmed | `low` |
| 片方向LLDP | candidate | `low` |
| 片方向description | candidate | `low` |

LLDPは補足証拠であり、0件でもdescription recordは破棄されない。LLDPとdescriptionが同じlocal interfaceで
異なる対向を示す場合、片方を消さずwarningとして残す。

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

1. confirmedとcandidateの件数を確認する。
2. candidateの対向hostname／interfaceをraw LLDPとrunning configで照合する。
3. warningがあるlocal interfaceはLLDPとdescriptionの両方を確認する。
4. mapping適用後のhostname／interfaceがinventoryの表記と一致することを確認する。
5. rule変更後は同一rawから再生成し、CSV差分を確認する。

CSV は決定的に sort し、処理完了後に atomic に置換する。入力 CSV header validation は未実装である。

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
