# AGENTS.md

電話帳画像から CSV（csv.gz）を生成する 3 段階 OCR パイプライン（Python）です。

## 仮想開発チーム

作業は Codex を統括役とする仮想開発チームで行います（全体運用: `F:\dev\HQ\TEAM.md`）。

| 役割 | 担当 | 使いどころ |
| --- | --- | --- |
| 統括・実装・最終確認 | Codex | 通常の実装、テスト、diff 確認、作業報告 |
| 設計・重要判断の助言 | Claude Code | パイプライン設計、OCR 精度評価、データモデル |
| 調査・検証 | Grok | 外部仕様の調査、ログ解析、互換性・動作検証 |

- API 料金節約のため、通常作業は 1 エージェントで完結させる。相談・委任は高リスクな変更か行き詰まったときだけにする。
- 委任するときは、目的・対象ファイル・禁止事項・期待する出力形式を明示する。
- コミット、プッシュ、デプロイ、公開、秘密情報の閲覧は、人間の明示的な指示があるときだけ行う。

### このプロジェクトの前提

- data/ の電話帳画像と output/ は巨大。git には src / doc / 設定例・小さな fixture だけを入れる。
- config.json に実 API キーが入っている可能性がある。キー値を出力や diff に含めない。
- 詳細は doc/pipeline.md ほか doc/ を参照。方針は F:\dev\HQ\PONKA-PLAN.md も参照。

## GitHub 接続用 SSH キー

このリポジトリは GitHub (`git@github.com:mimidesunya/...`) へ SSH で接続します。
接続用の鍵は `I:\SSH\GitHub-mimidesunya\ed25519` にあります。I: ドライブの鍵を
そのまま指定すると、権限が緩いため OpenSSH に拒否されることがあります。ローカルへ
コピーし、権限を現在のユーザーだけに絞ってから使ってください。

### セットアップ（PowerShell・初回のみ）

```powershell
$src = "I:\SSH\GitHub-mimidesunya\ed25519"
$dst = "$env:USERPROFILE\.ssh\GitHub-mimidesunya"
New-Item -ItemType Directory -Force "$env:USERPROFILE\.ssh" | Out-Null
Copy-Item $src $dst -Force
# 継承を切り、現在のユーザーにのみ読み取り権限を付与する
icacls $dst /inheritance:r /grant:r "$($env:USERNAME):(R)" | Out-Null
```

### Git に使わせる

このリポジトリ専用に設定する場合:

```powershell
git config core.sshCommand "ssh -i `"$env:USERPROFILE\.ssh\GitHub-mimidesunya`" -o IdentitiesOnly=yes"
```

その場限りで使う場合（環境変数）:

```powershell
$env:GIT_SSH_COMMAND = "ssh -i `"$env:USERPROFILE\.ssh\GitHub-mimidesunya`" -o IdentitiesOnly=yes"
git fetch
```

接続確認:

```powershell
ssh -i "$env:USERPROFILE\.ssh\GitHub-mimidesunya" -o IdentitiesOnly=yes -T git@github.com
```

> コピーした秘密鍵 (`%USERPROFILE%\.ssh\GitHub-mimidesunya`) はリポジトリにコミットしないこと。

