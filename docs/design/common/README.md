# Common Design

複数機能から共有されるCLI、入力、接続、収集、operation、schema、error、support artifactの設計をまとめる。

| 文書 | 責務 |
|---|---|
| [CLI, Configuration, and Resources Design](CLI_CONFIGURATION_AND_RESOURCES_DESIGN.md) | entrypoint、option、path探索、設定、resource、logging |
| [Inventory, Credentials, and Device Access Design](INVENTORY_CREDENTIALS_AND_DEVICE_ACCESS_DESIGN.md) | inventory、credential、SSH、NX-API、target解決 |
| [Terraform Inventory Generation Design](TERRAFORM_INVENTORY_GENERATION_DESIGN.md) | `hosts.yaml`／rolesからTerraform `main.tf`を生成 |
| [Collection Design](COLLECTION_DESIGN.md) | `collect-*`、raw、generation、manifest境界 |
| [External Running Config Import Design](EXTERNAL_RUNNING_CONFIG_IMPORT_DESIGN.md) | 外部show run folder／複数host transcriptの共通import |
| [Role Definition and Resolution Design](ROLE_DEFINITION_AND_RESOLUTION_DESIGN.md) | topology／function role、canonical resolver、provenance |
| [Operation State and Approval Design](OPERATION_STATE_AND_APPROVAL_DESIGN.md) | state、attempt、lock、approval、atomic publish |
| [Schema and Compatibility Policy](SCHEMA_AND_COMPATIBILITY_POLICY.md) | schema version、未知field、hash、互換性 |
| [Error Catalog](ERROR_CATALOG.md) | error code、終了code、retry、operator action |
| [Secret Scan Rule Catalog](SECRET_SCAN_RULE_CATALOG.md) | 共通・NX-OS secret検出rule、confidence、Manifest、fail-closed |
| [Portable Evidence Package Design](PORTABLE_EVIDENCE_PACKAGE_DESIGN.md) | 商用収集データの可搬化、用途profile、開示policy、offline利用 |
| [Support Bundle Design](SUPPORT_BUNDLE_DESIGN.md) | redaction、manifest、checksum、support引き渡し |

feature固有の判定やworkflowは[Network Operations Design](../network-ops/README.md)、containerlab、diagramは
それぞれの領域へ記載し、ここで再定義しない。
