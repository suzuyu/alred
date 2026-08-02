# Containerlab Instructions

## Scope

`init-clab`、`generate-clab`、`clab-transform-config`、`collect-clab`、
`check-clab-startup-config`、lab用config・topologyを変更または実行するときに適用する。

## Rules

- production source、sanitized fixture、生成lab artifactを区別し、出力先と変換元を明示する。
- 実在credential、管理IP、証明書、秘密鍵をstartup config、sample、fixtureへcommitしない。
- 既存CLI、README、CONFIG、testからAs-Isを確認し、設計書未記載を未実装とみなさない。
- 生成物は同じ入力から再現可能にし、入力mapping、role、site、merge順序を追跡可能にする。
- lab nodeへの変更はproduction機器への変更許可と混同せず、対象topologyとnodeを確認する。
- container runtimeや外部imageが必要な検証は前提、未実施理由、代替offline testを報告する。

## Sources

- [Design documentation coverage](../../docs/design/README.md)
- [Existing feature documentation status](../../docs/implementation/EXISTING_FEATURE_DOCUMENTATION_STATUS.md)
