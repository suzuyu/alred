# Security Policy

## Supported versions

開発中のalpha projectのため、原則として最新Releaseと`main`だけを修正対象とする。過去Releaseへ
security fixをbackportする場合は、各GitHub Releaseで明示する。

## Reporting a vulnerability

credential漏えい、任意command実行、不正な機器設定投入、redaction回避、artifact path traversalなどの
問題は、secretや実機情報を含む詳細を公開Issueへ投稿しない。

GitHubのPrivate vulnerability reportingが利用できる場合は、それを使用する。利用できない場合は、
repository ownerへGitHub経由で非公開の連絡方法を確認してから詳細を共有する。

報告には、可能な範囲で次を含める。

- 影響するalred versionまたはcommit
- 影響するcommandと実行方式
- 再現条件と最小のsanitized例
- 想定される影響
- 回避策の有無

password、token、private key、実在管理IP、未加工running config、operation workspace、support bundleを
報告本文へ直接含めない。

## GitHub and release safety

- Pull RequestのCIは実機へ接続しない。
- GitHub Actionsへ実機credentialを登録しない。
- Release assetは検証済みbinaryと対応するSHA-256だけとする。
- Draft Release作成と公開を分離し、公開には明示的な人の承認を必要とする。
