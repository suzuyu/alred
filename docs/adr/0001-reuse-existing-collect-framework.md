# ADR-0001: 既存collect基盤を再利用する

- Status: Accepted
- Date: 2026-07-26

## Context

Health CheckとOverlay変更管理にはNX-OSのshow command出力が必要である。専用Collectorを
新設すると、接続、認証、並列実行、rawログ保存が既存の`collect-*`と重複する。

## Decision

機器からの収集は既存`collect-*`を共通基盤として再利用する。Health Checkは収集成果物を
Collection Manifest経由で参照し、parser、Snapshot、evaluatorを収集処理から分離する。
外部CLI transcriptは専用importerで同じManifestとSnapshotへ正規化する。

## Consequences

- 既存collectとの重複実装を避けられる。
- 収集済みログからofflineで再解析できる。
- collect成果物の形式をadapterまたはManifestで安定化する必要がある。
- profileに基づく動的な追加収集は、既存collectとの責務境界を維持して実装する必要がある。

## References

- [Health Check Framework Design](../design/network-ops/HEALTH_CHECK_FRAMEWORK_DESIGN.md)
- [Overlay Change Management Design](../design/network-ops/OVERLAY_CHANGE_MANAGEMENT_DESIGN.md)
