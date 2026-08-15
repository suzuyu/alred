# Topology Generation

## 1. Canonical link

```bash
alred normalize-links \
  --hosts hosts.yaml \
  --input raw \
  --mappings mappings.yaml \
  --description-rules description_rules.yaml \
  --output-confirmed output/links_confirmed.csv \
  --output-candidates output/links_candidates.csv
```

LLDPとdescriptionは同じmapping／exclude規則で正規化される。双方向LLDP、LLDP＋description、片方向証拠を
区別し、曖昧なlinkを自動確定しない。

## 2. Containerlab YAML

```bash
alred generate-clab \
  --input output/links_confirmed.csv \
  --hosts hosts.lab.yaml \
  --min-confidence medium \
  --include-nodes \
  --group-by-role \
  --name network01 \
  --output output/topology.clab.yaml
```

merge順はgenerated、`clab-env`（`init-clab`のみ）、`clab-merge`、`clab-lab-profile`で、後の値が優先される。
port-channelはcontainerlabの物理endpointとして出力しない。

NX-OS 9000vの`startup-config`は、boot中のconfig投入停止を避けるため、既定では出力しない。boot後に
`clab-apply-config`または`push-config-dir`で投入する。merge／lab profileで明示したfieldは維持されるため、deploy前に確認し、
[NX-OS Boot and Config Push](05_NXOS_BOOT_AND_CONFIG_PUSH.md)の手順を参照する。

## 3. Runtime境界

生成YAMLを利用する外部command例:

```bash
containerlab inspect -t output/topology.clab.yaml
containerlab deploy -t output/topology.clab.yaml
```

これらはalredの処理ではない。実行前にcontainerlab version、image、license、bind path、権限を確認する。
外部CLIの最新仕様は[containerlab command reference](https://containerlab.dev/cmd/)を参照する。
