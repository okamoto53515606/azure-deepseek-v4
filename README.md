# DeepSeek V4 on Azure — 接続とデータ連携のチュートリアル

- 対象: Azure を利用しており、DeepSeek V4 に興味のある方。
- 用途: PoC（動作検証）。本番導入手順ではない
- 最終更新: 2026-09-12

この README は 2 部構成です。
| 部 | 内容 | 
|---|---|
| 第1部 | Azure で DeepSeek V4 を動かす（接続の確認まで） |
| 第2部 | データ連携と活用（BigQuery / SQL Server / レポート作成） |

料金、対応リージョン、モデル名は変わる可能性がある。作業当日に本文中の公式リンクを確認する。

第2部の第4章を検証用の Azure SQL で試す場合は、別紙 [Azure SQL 無料枠で在庫サンプルを用意する](docs/20260912_Azure%20SQL%20無料枠で在庫サンプルを用意する.md) を使う。

---

## 第1部: Azure で DeepSeek V4 を動かす

Azure 上で DeepSeek V4 Flash をデプロイし、`curl` と Python から接続できるところまで確認する。作業は Windows + WSL2（Ubuntu 24.04）で行う。

### この手順で行うこと

DeepSeek V4 は Azure 上で動作する。WSL2（Ubuntu）は、Windows PC から Azure の設定コマンドと接続確認コマンドを実行するために使う。

次の順番で動作を確認する。

1. Azure AI Foundry に DeepSeek V4 Flash をデプロイする。
2. `curl` で Azure AI に質問し、応答を確認する。
3. Python サンプルで Azure AI への接続を確認する。


### 1. 三案の比較

DeepSeek V4 を業務で使う経路は、大きく三つ。

| | A. 自前 GPU PC | B. DeepSeek 公式 API（中国） | C. 第三者がホスト |
|---|---|---|---|
| なにをするか | AI モデルを自社のマシンで動かす | `api.deepseek.com` に送る | Azure / Cloudflare 等が運用する API を呼び出す |
| 運用負荷 | 高い（ハードウェア、ドライバ、GPU メモリ、電源、冷却、障害対応） | 最も低い | 低い（クラウド事業者が運用） |
| データ経路 | 社内（閉域にできる） | **中国側の公式 API** | Azure の場合: リソースの保管は選択リージョンの geography。**推論は SKU 次第**（Global なら多国。後述） |
| 支払方法・ルート | 機材・電気・保守を**自社調達で支払う**。カードを DeepSeek / Azure に切らない | **DeepSeek 公式アカウント**（カード等）へトークン従量。請求先は中国側の公式 | **既存クラウドの請求**（本手順は Azure サブスク）。Cloudflare 等ならそちらのアカウント |
| コスト | **初期費用が大きい**（GPU、電源、冷却）。トークン課金はないが、未使用時も機材費が残る | **トークン単価は安いことが多い**。ハードウェアは不要。規制対応や移行の費用は別 | **ハードウェアは不要。トークンは公式より高いことが多い**が、PoC は数ドル規模 |
| 日本閉じ | 構成次第で可能 | 不可 | **通常は不可**（後述） |
| 向く用途 | 完全オフライン、厳密なデータレジデンシ | 個人検証、中国依存を許容できる場合 | **業務 PoC。推奨** |

#### A. ローカル GPU PC

- V4 Flash でも **284B クラス（活性化は小さい MoE）**。個人のノート GPU では現実的でないことが多い。量子化してもメモリ・消費電力・保守が重い。
- V4 Pro（1.6T 級）は個人・小チームの自前ホスト対象外と思ってよい。
- 「アプリを書く」以前に、**機材調達・CUDA・推論サーバ・監視**が仕事になる。
- 完全オフラインが絶対条件なら A。それ以外ではコスト対効果が悪い。

#### B. DeepSeek 公式 API（中国）

- 公式ホスト。プロンプトは **DeepSeek 社のサーバ（中国）** に行く。品質や価格とは別の、**管轄・経路の問題**。
- 規制業種、顧客契約、社内ポリシーで中国の API への送信が禁止されている場合、B は選択できない。

#### C. 第三者がホスト（推奨）

- 重みは DeepSeek だが、**推論は Azure / Cloudflare 等のインフラ**。契約・請求・SLA はそちら。
- アプリは OpenAI 互換の Chat Completions API を呼び出す。**コードの本体は変えず、接続先 URL、API キー、デプロイ名だけを変更できる。**
- A のハードウェア運用と、B の中国公式 API への依存をどちらも避けられるため、バランスがよい。

C の候補例（2026-09 時点。増減する）:

- **Microsoft Foundry（Azure）**: `DeepSeek-V4-Flash-0731` がカタログにある（Direct from Azure）。課金は Azure サブスク。本資料のチュートリアル対象。
- **Cloudflare Workers AI**: `@cf/deepseek-ai/deepseek-v4-flash-0731` および Pro。OpenAI 互換 `/v1/chat/completions` あり。Workers Paid または AI Gateway クレジットが必要。
- その他: Fireworks、Together、NVIDIA NIM、各種 AI Gateway など。いずれも「ホストが中国以外か」「契約・データ取り扱い」を個別確認。

**C でよくある誤解**

- 「Azure なら東京閉じ」→ **違う。** Foundry の DeepSeek V4 Flash は現状 **GlobalStandard 等が中心**で、日本リージョン閉じではない。East US にリソースを置いても、推論 SKU が Global なら処理リージョンは Azure 側のグローバル配置になる。
- 「日本の会社の Azure だから日本閉じ」→ **違う。** 契約者が日本でも、モデル SKU のリージョンが日本でなければ日本閉じではない。
- 「DeepSeek という名前なので中国へ送信される」→ **C では通常送信されない。** プロバイダが米国や欧州などでホストしていれば、公式 `api.deepseek.com` には送信されない。ただし **プロバイダのプライバシーとデータ所在地に関する文書は必ず確認する。**
- 「East US にリソースを置いたので推論も米国だけ」→ **GlobalStandard では誤り。** 保存場所と推論処理の場所は別であり、推論は下表の国へ振り分けられる可能性がある。

#### Azure Foundry DeepSeek でデータが「どの国」に行くか（本資料の SKU）

公式は **国名のホワイトリストを 1 本で固定しない**。「Global なら、そのモデルがデプロイされている Azure リージョンならどこでも処理してよい」と書く。顧客がリクエスト単位で国を指定することはできない。作業直前に [リージョン可用性](https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure-region-availability) を再確認すること（増減する）。

| 何のデータ | どこに行くか（本資料: East US リソース + `GlobalStandard` + DeepSeek-V4-Flash-0731） |
|---|---|
| **推論**（プロンプト・応答の処理。一時的。モデルはステートレス） | **下表の Azure 商用リージョンのいずれか**（容量で動的ルーティング）。1 か国閉じではない |
| **保存**（リソース設定、アップロード、Global / Data Zone 用の不正利用監視データなど） | リソースが属する **Azure geography（地域区分）**。East US なら **米国** |
| DeepSeek 社（中国）の公式 API | **行かない**（Foundry は Azure 上でホスト。OpenAI 等の外部 API にも出さない、と Microsoft が明記） |
| Azure **China**（`chinaeast` 等、21Vianet） | **この経路の候補に含まれない**（別クラウド）。商用 Azure の Global 表にも中国リージョンは無い |

**推論の候補国（Flash-0731 / Global Standard、公式表 2026-09 時点）**

Microsoft の表はリージョンコードだけなので、国に直すと次のとおり。**「必ずこの国」ではなく「処理され得る国」**。

| 地域 | リージョンコード | 国（データセンターの所在） |
|---|---|---|
| 米州 | `eastus` `eastus2` `centralus` `northcentralus` `southcentralus` `westus` `westus2` `westus3` `westcentralus` | **米国** |
| 米州 | `canadacentral` `canadaeast` | **カナダ** |
| 米州 | `brazilsouth` | **ブラジル** |
| 欧州 | `westeurope` | **オランダ** |
| 欧州 | `francecentral` | **フランス** |
| 欧州 | `germanywestcentral` | **ドイツ** |
| 欧州 | `uksouth` `ukwest` | **英国** |
| 欧州 | `swedencentral` | **スウェーデン** |
| 欧州 | `norwayeast` | **ノルウェー** |
| 欧州 | `switzerlandnorth` `switzerlandwest` | **スイス** |
| 欧州 | `italynorth` | **イタリア** |
| 欧州 | `spaincentral` | **スペイン** |
| 欧州 | `polandcentral` | **ポーランド** |
| アジア太平洋 | `japaneast` `japanwest` | **日本**（日本だけに固定されず、他国で処理される可能性もある） |
| アジア太平洋 | `koreacentral` | **韓国** |
| アジア太平洋 | `southindia` | **インド** |
| アジア太平洋 | `australiaeast` | **オーストラリア** |
| 中東・アフリカ | `uaenorth` | **アラブ首長国連邦** |
| 中東・アフリカ | `southafricanorth` | **南アフリカ** |

上表に **中国・香港・台湾・シンガポールは、この時点の Flash-0731 Global 表には出てこない**（`southeastasia` も 0731 の「other Foundry Models」APAC 列に無い）。ただし Microsoft はリージョンを予告なく足し得る。

**SKU を変えると「国」の意味が変わる**

| SKU | 推論の範囲 | 本モデル（0731） |
|---|---|---|
| **GlobalStandard**（本手順） | 上表の **全候補国** | あり。いちばん安い・広い |
| **DataZoneStandard** | ゾーン内のみ。US＝米国内、EU＝EU（+ EFTA のノルウェー／スイスを含む境界の定義）、APAC＝アジア太平洋の複数国 | 公式表では **V4-Flash（2026-04-23）** が米・欧にあり、**0731 の Data Zone 行は見当たらない**（要再確認）。APAC Data Zone は「other Foundry」で未掲載 |
| **Standard（リージョン）** | デプロイした **そのリージョンの国**（同一 geography 内の他リージョンへ運用上回ることは文書上あり） | DeepSeek 系は公式表で **Regional 未提供** が多い |

顧客が「米だけ」「EU だけ」と言うなら Global は使えない。Data Zone がカタログにあればそれ、無ければ別モデルか自前 GPU（A）。

補足（公式の約束の範囲）:

- プロンプト／応答は **他顧客・DeepSeek 社・基盤モデル学習には使わない**（[Data privacy](https://learn.microsoft.com/en-us/azure/foundry/responsible-ai/openai/data-privacy)）。
- どのリクエストがどの国の DC に行ったかは、ポータルから国名では取れない。
- 法務・DPIA の根拠は上の Learn と Product Terms / DPA。本表は説明用の要約。

---

### 2. なぜチュートリアルは Azure か

C の中でも Azure Foundry を手順化する理由。

1. **Bedrock / Vertex では、この資料の時点で V4 Flash を標準的なマネージドモデルとして利用しにくい。**
   Amazon Bedrock にあるのは DeepSeek-R1 / V3.1 / V3.2 など（東京含むリージョンあり）。**V4 Flash-0731 相当は、この時点では Azure Foundry や Cloudflare 側が先行。** 「AWS に全部寄せたい」は将来の話として、**今 V4 Flash を第三者がホストした形で試すなら Azure か Cloudflare。**
2. **請求を既存の Azure 契約にまとめられる。** 多くの事業会社はすでに Microsoft / Azure を持っている。カードを新たに Cloudflare や DeepSeek 公式に切らずに試せる。
3. **Foundry + Key Vault + 既存の情シス手続き**に乗せやすい。PoC でも「誰のサブスクで、どの RG か」が残る。

Cloudflare を選んでも「C」としては正しい。本手順が Azure なのは **契約とカタログの都合**であり、Cloudflare が劣るという意味ではない。Workers AI の Flash-0731 公表単価の一例は入力 $0.44 / 出力 $1.32 / キャッシュ入力 $0.014（100 万トークン、Workers Paid）。Azure の方が安いことが多いが、**必ずその時点の公式を見る。**

---

### 3. 料金の目安（必ずポータルで再確認）

単位は **USD / 100 万トークン**。契約・リージョン・SKU・為替で変わる。見積の根拠にはしない。

| 経路 | 入力 | キャッシュ入力 | 出力 | 出典（確認先） |
|---|---|---|---|---|
| Azure Foundry **DeepSeek-V4 Flash Global**（Serverless） | 0.19 | 0.028 | 0.51 | [Foundry Models pricing (DeepSeek)](https://azure.microsoft.com/en-us/pricing/details/ai-foundry-models/deepseek/) |
| Azure Foundry DeepSeek-V4 Pro Global | 1.74 | 0.145 | 3.48 | 同上 |
| Cloudflare Workers AI Flash-0731 | 0.44 | 0.014 | 1.32 | [Workers AI model page](https://developers.cloudflare.com/workers-ai/models/deepseek-v4-flash-0731/) |
| DeepSeek 公式 API | 公式サイトのその日の表 | （変動大） | （変動大） | DeepSeek 公式 Pricing |

PoC の感覚（Flash / Azure Global の上表を仮に使う場合）:

- 入力 10 万 + 出力 2 万トークン程度のレポート 1 本 → おおよそ **数セント**。
- 毎朝 1 本 × 月 20 営業日でも、モデル単体は **数ドル未満**になり得る。
- 高いのはモデルより、**データ取得と人が直す時間**側であることが多い。
- Azure ポータルの Cost Management と、上の公式料金ページを作業前に開くこと。

---

### 5. 作業手順（Windows + WSL2 Ubuntu 24.04）

`<PROXY_HOST>`、`<RESOURCE_GROUP>` などの `< >` 部分は、自社の値へ置き換える。

| 手順 | 接続確認の対象 | 失敗時に確認する担当 |
|---|---|---|
| 5.1〜5.3 | Windows、WSL、インターネット | 端末・ネットワーク管理者 |
| 5.4〜5.7 | Azure AI | Azure 管理者 |

#### 5.1 WSL を準備する

**実行場所: Windows の管理者 PowerShell**

WSL が未導入の場合だけ、次を実行する。

```powershell
wsl --install -d Ubuntu-24.04
```

再起動を求められたら Windows を再起動する。

PowerShellで以下のコマンドを実行してUbuntuを起動します。

```powershell
wsl -d Ubuntu-24.04
```

以降は、開いた Ubuntu 画面で実行する。

初回起動時は、新しいUNIXユーザーアカウントの設定が始まります。

画面の指示に従って以下を設定してください：

    user account: ubuntu (または任意のユーザー名)
    New password: ubuntu (任意のパスワード)

    ⚠️ 注意: パスワード入力時はセキュリティのため画面に文字が表示されませんが、入力は受け付けられています。


#### 5.2 会社プロキシを設定する（必要な会社のみ）

プロキシを使用しない会社では、この手順を飛ばして 5.3 へ進む。使用する場合は、値をネットワーク管理者に確認してから **WSL の Ubuntu** で実行する。

```bash
export http_proxy="http://<PROXY_HOST>:<PROXY_PORT>"
export https_proxy="http://<PROXY_HOST>:<PROXY_PORT>"
export HTTP_PROXY="$http_proxy"
export HTTPS_PROXY="$https_proxy"
export no_proxy="localhost,127.0.0.1,.local"
export NO_PROXY="$no_proxy"
```

この設定は現在のターミナルを閉じると消える。継続利用する場合は、同じ `export` 行を `~/.bashrc` の末尾へ追加する。認証用パスワードが必要な会社では、保存方法をネットワーク管理者に確認する。

Ubuntu のパッケージ管理コマンド `apt` にも設定する。

```bash
sudo tee /etc/apt/apt.conf.d/95proxy >/dev/null <<EOF
Acquire::http::Proxy "http://<PROXY_HOST>:<PROXY_PORT>";
Acquire::https::Proxy "http://<PROXY_HOST>:<PROXY_PORT>";
EOF
```

確認:

```bash
curl -sS -o /dev/null -w "%{http_code}\n" https://aka.ms/InstallAzureCLIDeb
```

**成功の目印:** `200`、`301`、`302` のいずれかが表示される。

証明書エラーが出た場合は、会社の SSL 検査用 CA 証明書が必要。証明書検証を無効にせず、ネットワーク管理者へ確認する。

#### 5.3 リポジトリと `uv` を確認する

**実行場所: WSL の Ubuntu**

okamoがgithubに準備した
[サンプルコード](https://raw.githubusercontent.com/okamoto53515606/azure-deepseek-v4/main/dsv4_wsl_poc_agent.py)
をダウンロードします。

```bash
curl -O https://raw.githubusercontent.com/okamoto53515606/azure-deepseek-v4/main/dsv4_wsl_poc_agent.py
```
注意）
WSL2 の DNS 設定が不正な状態になると、git pull や AWS API 呼び出しが失敗することがあります。DNS を 8.8.8.8 に書き換えます。
echo 'nameserver 8.8.8.8' | sudo tee /etc/resolv.conf


Python パッケージ管理ツール `uv` をインストールする。

```bash
command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
source "$HOME/.local/bin/env"
uv --version
```

**成功の目印:** `uv 0.x.x` のようにバージョンが表示される。

#### 5.4 Azure CLI へログインする

**実行場所: WSL の Ubuntu**

```bash
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
az version
az login
az account list --output table
```

ブラウザが開かない場合は `az login --use-device-code` を使う。

```bash
az account set --subscription "9f05b316-4dda-41ce-9ba6-04851d7549ce"
az account show --query '{name:name,id:id,tenantId:tenantId}' --output table
```

**成功の目印:** 使用するサブスクリプションの名前、ID、テナント ID が表示される。

#### 5.5 Azure AI リソースとモデルを作成する

リージョン例は **eastus**（カタログで Flash-0731 が取れることが多い。**日本リージョン閉じではない**）。

```bash
export RG="<RESOURCE_GROUP>"
export LOC="eastus"
export ACCOUNT="<ACCOUNT_NAME>"       # 小文字・数字。カスタムドメインになる
export DEPLOY="DeepSeek-V4-Flash-0731"

printf 'RG=%s\nLOC=%s\nACCOUNT=%s\nDEPLOY=%s\n' "$RG" "$LOC" "$ACCOUNT" "$DEPLOY"

az group create -n "$RG" -l "$LOC"

az cognitiveservices account create \
  -n "$ACCOUNT" -g "$RG" \
  --custom-domain "$ACCOUNT" \
  --location "$LOC" \
  --kind AIServices \
  --sku S0
```
注意）
(MissingSubscriptionRegistration) The subscription is not registered to use namespace 'Microsoft.CognitiveServices'エラーがでる場合
Azure Portal にサインインします。「サブスクリプション」を検索して選択します。エラーが発生している対象のサブスクリプション名をクリックします。左メニューの「設定」項目にある「リソース プロバイダー」をクリックします。検索ボックスに Microsoft.CognitiveServices と入力します。一覧に表示された Microsoft.CognitiveServices を選択し、上部の「登録」ボタンをクリックします。登録状態が「登録済み」に変わるまで数分待ちます。

初めて作業する場合は、[Foundry カタログ DeepSeek-V4-Flash-0731](https://ai.azure.com/catalog/models/DeepSeek-V4-Flash-0731) から作成済みの AI Services アカウントを選び、ポータル画面でデプロイする方法を推奨する。デプロイ方式は `GlobalStandard`、デプロイ名は `$DEPLOY` と同じ値にする。

CLI でデプロイする場合は、最初にそのアカウントで利用可能なモデル情報を表示する。

```bash
az cognitiveservices account list-models -n "$ACCOUNT" -g "$RG" \
  --query "[?name=='DeepSeek-V4-Flash-0731'].{name:name,version:version,format:format}" \
  --output table
```

表示された `version` と `format` を次へ設定する。

```bash
export MODEL_VERSION="<一覧に表示された version>"
export MODEL_FORMAT="<一覧に表示された format>"

az cognitiveservices account deployment create \
  -n "$ACCOUNT" -g "$RG" \
  --deployment-name "$DEPLOY" \
  --model-name "DeepSeek-V4-Flash-0731" \
  --model-version "$MODEL_VERSION" \
  --model-format "$MODEL_FORMAT" \
  --sku-capacity 1 \
  --sku-name "GlobalStandard"
```

注意）
Azureの無料試用版（200ドルの無料クレジット）だと、以下エラーになります。
(InsufficientQuota) This operation require 1 new capacity in quota Requests Per Minute - DeepSeek-V4-Flash-0731, which is bigger than the current available capacity 0. The current quota usage is 0 and the quota limit is 0 for quota Requests Per Minute - DeepSeek-V4-Flash-0731.
Code: InsufficientQuota
Message: This operation require 1 new capacity in quota Requests Per Minute - DeepSeek-V4-Flash-0731, which is bigger than the current available capacity 0. The current quota usage is 0 and the quota limit is 0 for quota Requests Per Minute - DeepSeek-V4-Flash-0731.

```bash
az cognitiveservices account deployment show \
  -n "$ACCOUNT" -g "$RG" --deployment-name "$DEPLOY" \
  --query '{name:name,provisioningState:properties.provisioningState}' --output table
```

**成功の目印:** `provisioningState` が `Succeeded`。

#### 5.6 Azure AI の接続情報を設定する

```bash
export AZURE_AI_ENDPOINT="$(az cognitiveservices account show -n "$ACCOUNT" -g "$RG" --query properties.endpoint -o tsv | sed 's:/*$::')"
export AZURE_AI_API_KEY="$(az cognitiveservices account keys list -n "$ACCOUNT" -g "$RG" --query key1 -o tsv)"
export AZURE_AI_DEPLOYMENT="$DEPLOY"

echo "endpoint=$AZURE_AI_ENDPOINT"
test -n "$AZURE_AI_API_KEY" && echo "api_key=set"
```

**成功の目印:** `endpoint=https://...` と `api_key=set` が表示される。

#### 5.7 Azure AI だけを確認する

最初に `curl` で確認する。これにより、Python の問題と Azure の問題を分けて判断できる。

```bash
curl -sS --fail-with-body "${AZURE_AI_ENDPOINT}/openai/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "api-key: ${AZURE_AI_API_KEY}" \
  -d "{
    \"model\": \"${AZURE_AI_DEPLOYMENT}\",
    \"messages\": [
      {\"role\": \"user\", \"content\": \"1+1は？数字だけ答えて。\"}
    ],
    \"max_tokens\": 128
  }"
```

**成功の目印:** 応答 JSON の `choices` → `message` → `content` に `2` が入る。

| エラー | 最初に確認するもの |
|---|---|
| `401` / `Unauthorized` | `AZURE_AI_API_KEY` |
| `404` / `Not Found` | `AZURE_AI_ENDPOINT` と `AZURE_AI_DEPLOYMENT` の組み合わせ |
| `429` | 利用上限、割り当て、再試行までの待ち時間 |
| `400` | モデル名、モデル形式、SKU、リクエスト形式 |
| 接続・証明書エラー | 会社プロキシ、CA 証明書、DNS |



```bash
cd ~
uv init --bare 
uv add strands-agents openai
uv run python dsv4_wsl_poc_agent.py --ping-llm
```

**成功の目印:** 最後に `llm_response=2` と表示される。この確認では Azure AI だけを呼び出す。

---

## 第2部: データ連携と活用

- 対象: アプリケーション開発エンジニア
- 用途: PoC（動作検証）。本番導入手順ではない
- 作成日: 2026-09-12

第2部は、第1部（旧・前編）を完了した人向けの続編。第1部の作業が終わっていることを前提にする。

料金、対応リージョン、モデル名は変わる可能性がある。作業当日に本文中の公式リンクを確認する。

### 0. 始める前に

#### 前提条件

第1部で次の作業が完了していることを確認する。

| 確認内容 | 完了の目印 |
|---|---|
| WSL2 Ubuntu | `whoami` と `lsb_release -ds` が表示される |
| リポジトリと `uv` | `uv --version` が表示される |
| Azure AI のモデル | `DeepSeek-V4-Flash-0731` のデプロイが `Succeeded` |
| Azure AI の環境変数 | `AZURE_AI_ENDPOINT`、`AZURE_AI_API_KEY`、`AZURE_AI_DEPLOYMENT` の値を控えている（0 章で `.env` に記入する） |
| 後片付け用の値 | `AZURE_RG`（第1部で作ったリソースグループ）と `AZURE_AI_ACCOUNT`（AI リソース名）も控えている |
| Azure AI の接続 | `--ping-llm` の結果が `llm_response=2` |

`llm_response=2` をまだ確認していない場合は、第2部を進めず、第1部を完了する。

ターミナルを開き直すと `export` した値は消える。そこで第2部では、第1部の Azure AI の値を含めて `.env` ファイル 1 つにまとめる。

#### 環境変数は `.env` にまとめる

第1部では `export` で環境変数を設定した。第2部では、第1部で設定した Azure AI の値を含めて `.env` にまとめる。読み込ませ方は次の 2 通り。

| 使う場面 | 読み込ませ方 |
|---|---|
| Python のサンプル | `uv run --env-file .env python dsv4_wsl_poc_agent.py ...` |
| `gcloud` / `bq` / `curl` | `set -a; . ./.env; set +a` を実行してから使う |

サンプルは `.env` を自動では読まない。`--env-file .env` を付けたときだけ値が渡る。

`dsv4_wsl_poc_agent.py` があるディレクトリで、第1部の値を使って `.env` を作成する。`< >` の値は第1部で使ったものに置き換える。

```bash
cat > .env <<'EOF'
# Azure AI（第1部で設定した値）
AZURE_AI_ENDPOINT="https://<RESOURCE_NAME>.cognitiveservices.azure.com"
AZURE_AI_API_KEY="<API_KEY>"
AZURE_AI_DEPLOYMENT="DeepSeek-V4-Flash-0731"
# 第7章の後片付けで使う（第1部で az group create したリソースグループと AI リソース）
AZURE_RG="<RESOURCE_GROUP>"
AZURE_AI_ACCOUNT="<AI_RESOURCE_NAME>"

# BigQuery とサービスアカウントの値は、第2章の 2.7 で追記する

# 会社のプロキシが必要な場合だけ、第1部で設定した値を使う（# を外す）
# https_proxy="http://<PROXY_HOST>:<PROXY_PORT>"
# http_proxy="http://<PROXY_HOST>:<PROXY_PORT>"
EOF

chmod 600 .env
grep -c . .env   # 書き込めた行数を確認する（値は表示しない）
```

`.env` は [.gitignore](.gitignore) で除外されているため Git には登録されない。ただし API キーが入るファイルなので、画面への貼り付け、チャットやメールへの添付、作業報告書への転記をしない。第7章で削除する。

#### 使用するライブラリを最初にまとめて追加する

第2部で使うライブラリを最初にまとめて追加する。初回だけ 1 分ほどかかるが、以降は `--with` を書かずに `uv run` だけで実行できる。追加した内容は `pyproject.toml` と `uv.lock` に記録されるため、別の端末では `uv sync` で同じ環境を再現できる。

```bash
uv add google-cloud-bigquery python-docx matplotlib
```

| 追加するライブラリ | 用途 |
|---|---|
| `google-cloud-bigquery` | 3.2 の `--ping-bq`（BigQuery SDK 直結の確認） |
| `python-docx` | 3.7 と 4.4 の Word レポート作成 |
| `matplotlib` | `write_chart_png` のグラフ。使わない場合は省いてよい |

**成功の目印:** `+ python-docx` のような追加されたライブラリの行が表示され、最後にエラーが出ない。2 回目以降の実行は数秒で終わる。

#### Azure AI のレート制限を確認する（429 対策）

第2部では、1 回の実行の中でエージェントが Azure AI へ何度も要求を送る。Azure のデプロイには「1 分あたりのリクエスト数（RPM）」と「1 分あたりのトークン数（TPM）」の上限があり、超えると `429`（`RateLimitReached`）が返る。この上限は**デプロイの `capacity` に比例**し、DeepSeek のような Foundry モデル（MaaS）の最小値は `capacity 1` で、RPM 1・TPM 1,000 しかない。この状態では 3.5 以降の実行は 1 回目から 429 になる。

| デプロイの capacity | リクエスト上限 | トークン上限 | この資料での実行 |
|---:|---:|---:|---|
| 1 | 1 / 分 | 1,000 / 分 | 不可（1 回目から 429） |
| 20 | 20 / 分 | 20,000 / 分 | 動作確認済み（2026-09-12） |

TPM には**入力プロンプトに加えて `max_tokens` も含まれる**。サンプルは 1 回の要求で大きめの `max_tokens` を指定するため、TPM が小さいデプロイでは 1 回の要求だけで上限に達する。

**上限の確認（応答ヘッダー）:** 次のコマンドは上限と残量を表示する。`curl` は `.env` を直接読まないため、先にシェルへ読み込む。`--http1.1` を付けているのは、この WSL 環境では HTTP/2 のままだと応答が返らず、コマンドが止まってしまうため。

```bash
set -a; . ./.env; set +a

curl -sS --http1.1 -D - -o /dev/null \
  -X POST "${AZURE_AI_ENDPOINT}/openai/v1/chat/completions" \
  -H "Content-Type: application/json" \
  -H "api-key: ${AZURE_AI_API_KEY}" \
  -d "{\"model\":\"${AZURE_AI_DEPLOYMENT}\",\"messages\":[{\"role\":\"user\",\"content\":\"1+1?\"}],\"max_tokens\":16}" \
  | grep -i -E 'HTTP/|ratelimit'
```

**成功の目印:** `HTTP/1.1 200 OK` に続いて、`x-ratelimit-limit-requests: 20`、`x-ratelimit-limit-tokens: 20000` のような行が表示される。

**上限の確認（Azure CLI）:** `az` が使える場合は、デプロイの設定とサブスクリプションのクォータを直接確認できる。

```bash
set -a; . ./.env; set +a

az cognitiveservices account deployment show \
  -g "$AZURE_RG" -n "$AZURE_AI_ACCOUNT" \
  --deployment-name "$AZURE_AI_DEPLOYMENT" \
  --query "{capacity:sku.capacity, rateLimits:properties.rateLimits}" -o json

az cognitiveservices usage list -l "<REGION>" \
  --query "[?contains(name.value,'DeepSeek')].{name:name.value,current:currentValue,limit:limit}" -o table
```

**上限の引き上げ:** Foundry ポータルでは「デプロイ（Deployments）」で対象デプロイを開き、レート制限を変更する。Azure CLI には `update` サブコマンドが無いため、同じモデルを指定して作成し直す。

```bash
set -a; . ./.env; set +a

az cognitiveservices account deployment create \
  -g "$AZURE_RG" -n "$AZURE_AI_ACCOUNT" \
  --deployment-name "$AZURE_AI_DEPLOYMENT" \
  --model-format DeepSeek \
  --model-name "<MODEL_NAME>" \
  --model-version "<MODEL_VERSION>" \
  --sku-name GlobalStandard \
  --sku-capacity 20
```

`<MODEL_NAME>` と `<MODEL_VERSION>` は、`az cognitiveservices account deployment show` の `--query model -o json` に出る `name` と `version` をそのまま使う。`--sku-capacity` は `az cognitiveservices usage list` の `limit` の範囲内で指定する。上限まで使うと他のデプロイに割り当てられなくなる点に注意する。MaaS の `capacity` はレート制限のみで、時間単位の課金は発生しない。

これでも `429` が再発する場合は、3.5 のプロンプトを短くする、取得する行数を減らす、`max_tokens` を小さくする、`capacity` をさらに上げる（クォータ増加の申請が必要）、の順で対処する。

#### sudo をパスワードなしにする（検証端末のみ）

第2章以降は `sudo apt-get` などを何度も実行する。検証用の WSL 端末に限り、`ubuntu` ユーザーの `sudo` をパスワードなしにすると作業が止まりにくい。**共用端末や本番端末では実行しない。** 作業が終わったら「設定を戻す」を実行する。

```bash
echo "ubuntu ALL=(ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/ubuntu-nopasswd >/dev/null && sudo chmod 0440 /etc/sudoers.d/ubuntu-nopasswd && sudo visudo -c
```

**成功の目印:** `visudo -c` が `/etc/sudoers.d/ubuntu-nopasswd: parsed OK` と表示する。

`whoami` が `ubuntu` 以外の場合は、コマンド内の `ubuntu` を自分のユーザー名に置き換える。

設定を戻す場合は次を実行する。

```bash
sudo rm /etc/sudoers.d/ubuntu-nopasswd
```

#### この資料で行うこと

1. このチュートリアル専用の使い捨てサービスアカウントを Google Cloud に作成する。
2. BigQuery SDK で接続を切り分ける。
3. Azure 上の DeepSeek から MCP Toolbox 経由で BigQuery を読み取る。
4. Word レポートを Windows の C ドライブへコピーする。
5. 応用例として、SQL Server の在庫データから日次レポートを作る。
6. GA4・GSCのWebレポートや、Oracleなどの業務データへ広げる案を確認する。
7. チュートリアル用の鍵とサービスアカウントを削除する。

#### 完了の目安

| 確認内容 | 成功時の目印 |
|---|---|
| BigQuery SDK 単体 | `"ok": 1` |
| BigQuery MCP 起動 | `list_table_ids` と `execute_sql` が表示される |
| DeepSeek → BigQuery MCP | テーブル一覧と `SELECT ... LIMIT 5` が成功する |
| Word レポート | `C:\DeepSeekV4PoC\reports` に作成され、Windows から開ける |
| SQL Server（任意） | Toolbox 起動後、読み取り専用ユーザーで `SELECT 1` が成功する |
| 後片付け | JSON 鍵と使い捨てサービスアカウントを削除する |

`<PROJECT_ID>` のように `< >` で囲まれた値は、そのまま入力せず自社の値に置き換える。

---

### 1. BigQuery 用のサンプルと認証方式を確認する

ここからは、Azure AI に加えて BigQuery を読み取る。サンプル本体は [dsv4_wsl_poc_agent.py](dsv4_wsl_poc_agent.py)。設定処理も含む1ファイルで、`config.py` などの設定ファイルを読み込まない。値は 0 章で作成した `.env` を `--env-file .env` で渡し、担当者がコマンドを実行したときだけ動く。

サンプルの主な制限は次のとおり。

- BigQuery の SQL は `SELECT` または `WITH` で始まるものだけを許可する。
- 1 回に返す結果は最大 200 行。
- GCP サービスアカウントの権限があるデータだけを読める。
- 作業ファイルは `generated_files/dsv4_wsl_poc/` に作る。
- `cleanup_work_files` は一時ファイルを削除し、Word ファイルは残す。

認証には、第2章で新しく作る **チュートリアル専用の使い捨てサービスアカウントと JSON 鍵**を使う。既存のサービスアカウントや既存の鍵は使わない。これにより、作業終了後にこのチュートリアルで作成した認証情報だけを特定して削除できる。

JSON 鍵の中身は `cat` で表示せず、Git、チャット、メール、作業報告書へ貼り付けない。既定のファイル名 `xxx.json` は [.gitignore](.gitignore) で除外済み。第7章の後片付けが終わるまで、作成したSAのメールアドレスを確認できるようにしておく。

---

### 2. 使い捨ての GCP サービスアカウントを作成する

サービスアカウント（SA）はプログラム専用の Google Cloud アカウント。このチュートリアルでは新しいSAと鍵を作成し、確認終了後に両方を削除する。作成と権限付与は、管理権限を持つ自分の Google アカウントで行う。組織ポリシーで JSON 鍵の作成が禁止されている場合は、回避せず Google Cloud 管理者へ相談する。

#### 2.1 `gcloud` CLI をインストールする

公式: [Install the Google Cloud CLI（Debian/Ubuntu）](https://docs.cloud.google.com/sdk/docs/install#deb)

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates gnupg curl

curl https://packages.cloud.google.com/apt/doc/apt-key.gpg \
  | sudo gpg --dearmor -o /usr/share/keyrings/cloud.google.gpg

echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
  | sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list

sudo apt-get update && sudo apt-get install -y google-cloud-cli
gcloud version
```

会社プロキシ下では、シェルの `https_proxy` に加え [gcloud のプロキシ設定](https://docs.cloud.google.com/sdk/docs/proxy-settings) が必要なことがある。

```bash
gcloud config set proxy/type http
gcloud config set proxy/address "<PROXY_HOST>"
gcloud config set proxy/port "<PROXY_PORT>"
```

#### 2.2 Google Cloud へログインし、作業値を設定する

`SA_PROJECT` はサービスアカウントを作るプロジェクト、`BQ_PROJECT` は読み取る BigQuery データがあるプロジェクト。同じ場合は同じ値を入れる。

この章の `gcloud` と `bq` は `.env` を読まないため、最初に 0 章で作った `.env` をシェルへ読み込む。

```bash
set -a; . ./.env; set +a

gcloud auth login --no-launch-browser   # デバイスコード
# またはブラウザが使えるなら: gcloud init

export SA_PROJECT="<SERVICE_ACCOUNT_PROJECT_ID>"
export BQ_PROJECT="<BIGQUERY_DATA_PROJECT_ID>"
export BQ_DATASET="<DATASET_ID>"
export BQ_TABLE="<TABLE_ID>"
# 日時を付け、既存SAと重複しないチュートリアル専用IDを作る
export SA_ID="deepseek-poc-$(date +%Y%m%d%H%M%S)"
export SA_EMAIL="${SA_ID}@${SA_PROJECT}.iam.gserviceaccount.com"
export KEY_JSON="$PWD/xxx.json"

if [[ -e "$KEY_JSON" ]]; then
  echo "[STOP] $KEY_JSON は既に存在します。既存鍵は使用せず、ここで作業を止めてください。"
else
  echo "[OK] 新しい鍵を作成できるパスです: $KEY_JSON"
fi

printf 'SA_PROJECT=%s\nBQ_PROJECT=%s\nBQ_DATASET=%s\nBQ_TABLE=%s\nSA_EMAIL=%s\n' \
  "$SA_PROJECT" "$BQ_PROJECT" "$BQ_DATASET" "$BQ_TABLE" "$SA_EMAIL"
gcloud config set project "$SA_PROJECT"
gcloud auth list
```

`[STOP]` または `printf` の表示に `<...>` が出たら、2.3以降へ進まない。既存の `xxx.json` は別用途の鍵かもしれないため、この手順で上書きも削除もしない。管理者へ所有者を確認し、鍵が存在しない作業ディレクトリを用意して2.2からやり直す。

`SA_EMAIL` は後片付けで使う。ターミナルを閉じる前に第7章まで実施するか、表示されたメールアドレスを秘密情報を含まない作業メモへ控える。

#### 2.3 サービスアカウントを作成する

```bash
gcloud iam service-accounts create "$SA_ID" \
  --project="$SA_PROJECT" \
  --display-name="$SA_ID" \
  --description="DeepSeek V4 BigQuery チュートリアル用。作業後に削除"

gcloud iam service-accounts describe "$SA_EMAIL"
```

作成直後は反映待ちで失敗することがある。数十秒空けて再実行する。

#### 2.4 必要な API を有効化する

```bash
gcloud services enable iam.googleapis.com --project="$SA_PROJECT"
gcloud services enable bigquery.googleapis.com --project="$BQ_PROJECT"
```

#### 2.5 BigQuery の読み取り権限を付ける

クエリの実行には **BigQuery Job User**、データの閲覧には **BigQuery Data Viewer** が必要。Data Viewer は対象データセットだけに付ける方法を推奨する。

```bash
# クエリを実行するプロジェクトに付与
gcloud projects add-iam-policy-binding "$BQ_PROJECT" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/bigquery.jobUser"

# 読み取るデータセットだけに付与（推奨）
bq query --use_legacy_sql=false --project_id="$BQ_PROJECT" \
  "GRANT \`roles/bigquery.dataViewer\` ON SCHEMA \`${BQ_PROJECT}.${BQ_DATASET}\` TO \"serviceAccount:${SA_EMAIL}\";"
```

`GRANT` 自体が権限不足で失敗した場合は、Google Cloud 管理者へ依頼する。このチュートリアルでは対象データセット以外を読めるようにする必要はないため、代わりにプロジェクト全体の Data Viewer を付けない。

Job User の付与を確認する。

```bash
gcloud projects get-iam-policy "$BQ_PROJECT" \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:${SA_EMAIL}" \
  --format="table(bindings.role)"
```

データセット単位の Data Viewer は上のプロジェクト IAM 表には表示されない。実際の読み取り可否は 3.2 の `--ping-bq` と対象テーブルへの `SELECT` で確認する。

#### 2.6 JSON 鍵を作成する

組織で `iam.disableServiceAccountKeyCreation` が有効だと失敗する。その場合は情シスへ相談する。鍵は最大 10 個。Git に置かず、権限を `600` にする。

```bash
# リポジトリで使う既定名。別パスなら GOOGLE_APPLICATION_CREDENTIALS を後で export
gcloud iam service-accounts keys create "$KEY_JSON" \
  --iam-account="$SA_EMAIL" \
  --key-file-type=json

chmod 600 "$KEY_JSON"
# 中身は出さない。存在と形式だけ見る
ls -l "$KEY_JSON"
python3 -c "import json,sys; json.load(open(sys.argv[1])); print('json_ok')" "$KEY_JSON"

export GOOGLE_APPLICATION_CREDENTIALS="$KEY_JSON"
export GOOGLE_BIGQUERY_PROJECT="$BQ_PROJECT"
export GOOGLE_BIGQUERY_LOCATION="asia-northeast1"
```

`GOOGLE_BIGQUERY_LOCATION` は対象データセットのロケーションに合わせる。東京リージョンなら `asia-northeast1`、US マルチリージョンなら `US`。US 単一リージョンの場合は `us-central1` のようにリージョン名を指定する。不明な場合は BigQuery 管理者へ確認する。

`bq show --format=prettyjson "${BQ_PROJECT}:${BQ_DATASET}" | grep -i '"location"'` を実行すると、対象データセットのロケーションを確認できる。`"US"` なら US マルチリージョン、`"us-central1"` のようにリージョン名が返ればその単一リージョンに合わせる。

サンプルは `GOOGLE_APPLICATION_CREDENTIALS` が未設定の場合、現在ディレクトリにある `xxx.json` を使う。

#### 2.7 `.env` に BigQuery の設定を追記する

0 章で作った `.env` に、2.2〜2.6 で設定した値をまとめて追記する。いまシェルに入っている値をそのまま書き出すので、値の打ち直しは不要。パスワードなどは含まれない。**2.2〜2.6 を実行したのと同じターミナルで行う。**

```bash
# 値が空のまま書き込まないための確認
: "${SA_EMAIL:?2.2 の値を設定してから実行してください}"

cat >> .env <<EOF

# BigQuery とサービスアカウント（2.2〜2.6 で設定した値）
SA_PROJECT="$SA_PROJECT"
BQ_PROJECT="$BQ_PROJECT"
BQ_DATASET="$BQ_DATASET"
BQ_TABLE="$BQ_TABLE"
SA_ID="$SA_ID"
SA_EMAIL="$SA_EMAIL"
KEY_JSON="$KEY_JSON"
GOOGLE_APPLICATION_CREDENTIALS="$GOOGLE_APPLICATION_CREDENTIALS"
GOOGLE_BIGQUERY_PROJECT="$GOOGLE_BIGQUERY_PROJECT"
GOOGLE_BIGQUERY_LOCATION="$GOOGLE_BIGQUERY_LOCATION"
EOF

chmod 600 .env
grep -c . .env   # 行数が増えたことを確認する（値は表示しない）
```

**成功の目印:** `grep -c . .env` の数が 0 章より増えている。

これで第3章以降は、ターミナルを開き直しても `uv run --env-file .env ...` だけで実行できる。`gcloud` や `bq` を使うときだけ `set -a; . ./.env; set +a` を先に実行する。

---

### 3. 設定確認、BigQuery 単体確認、全体実行を行う

この章の Python コマンドはすべて `--env-file .env` を付ける。`export` をやり直す必要はない。第2章 2.7 で `.env` を作成していない場合は、先に 2.7 を実施する。

`uv run` は「今いるディレクトリ（または親）の `pyproject.toml`」を使う。**コマンドは `dsv4_wsl_poc_agent.py` があるディレクトリで実行する**。別の場所から実行する場合は `uv run --project <リポジトリのパス> ...` を使う。環境を作り直す場合は、そのフォルダで `uv sync` を実行する。

#### 3.1 ローカル設定だけを確認する

このコマンドは環境変数、API キーの有無、JSON 鍵の形式を確認する。Azure AI と BigQuery へテスト要求は送らず、秘密の値も表示しない。スクリプトは `.env` や Key Vault を直接読み込まず、`--env-file` で渡された値だけを使う。

```bash
uv run --env-file .env python dsv4_wsl_poc_agent.py --check-config
```

**成功の目印:** 最後に `[OK] 設定を確認しました。Azure AI と BigQuery へのテスト要求はまだ送っていません。` と表示される。

#### 3.2 BigQuery SDK で単体確認する

これは障害切り分け用の確認で、**DeepSeek と MCP Toolbox は通らない**。Python から BigQuery へ直接 `SELECT 1` を実行する。

```bash
uv run \
  --env-file .env \
  python dsv4_wsl_poc_agent.py --ping-bq
```

**成功の目印:** `bq_response=` に続く JSON に `"ok": 1` が入る。

**動作確認（2026-09-12）:** サービスアカウント認証による `SELECT 1` が成功済み。資料には実在するプロジェクト ID、アカウント名、リソース名、鍵 ID を記録しない。

```text
bq_response={"ok": 1, "project": "<BIGQUERY_PROJECT_ID>", "location": "<BIGQUERY_LOCATION>"}
```

この確認は固定値を返すクエリなので、BigQuery のテーブルデータは読んでいない。実際のテーブルを読む場合は、2.5 の手順で対象データセットに `roles/bigquery.dataViewer` を追加する。

| 主なエラー | 最初に確認するもの |
|---|---|
| `403` / `Access Denied` | Job User と Data Viewer の付与先、SA メールアドレス |
| `Not found ... location` | `GOOGLE_BIGQUERY_LOCATION` とデータセットのロケーション |
| JSON 鍵が見つからない | `GOOGLE_APPLICATION_CREDENTIALS`、ファイル名、現在のディレクトリ |
| `ModuleNotFoundError: google.cloud` | 0 章の `uv add google-cloud-bigquery` を実行したか確認する |
| `No module named 'strands'` / `'openai'` | 実行場所を確認する。`dsv4_wsl_poc_agent.py` があるフォルダで実行するか、そのフォルダで `uv sync` を実行する |
| `No module named 'docx'` | 0 章の `uv add python-docx` を実行したか確認する（3.7 / 4.4） |
| `No module named 'matplotlib'` | 0 章の `uv add matplotlib` を実行したか確認する（グラフを使う場合） |
| `429` / `RateLimitReached` / `OpenAI threw rate limit error` | Azure AI デプロイのレート制限（RPM / TPM）。0 章「Azure AI のレート制限を確認する」で確認し、`capacity` を引き上げる |
| `curl` が応答せず止まる | `--http1.1` を付ける |
| `RuntimeError: generator didn't stop after athrow()` | 終了時の後片付けノイズ。回答は成功している。サンプルは `an error occurred during closing of asynchronous generator` の 1 件だけを自動で除外する |

#### 3.3 MCP Toolbox をインストールする

[MCP Toolbox の公式リリース](https://github.com/googleapis/mcp-toolbox/releases/latest)で最新バージョンと CPU 種別を確認する。次は 2026-09-10 時点の v1.11.0、Linux x86_64 用。

```bash
uname -m
export TOOLBOX_VERSION="1.11.0"
mkdir -p "$HOME/.local/bin"
curl -fL \
  "https://storage.googleapis.com/mcp-toolbox-for-databases/v${TOOLBOX_VERSION}/linux/amd64/toolbox" \
  -o "$HOME/.local/bin/toolbox"
chmod +x "$HOME/.local/bin/toolbox"
export PATH="$HOME/.local/bin:$PATH"
toolbox --version
```

**成功の目印:** `toolbox version 1.11.0` のように表示される。`uname -m` が `aarch64` の場合は公式リリースページにある Linux ARM64 用 URL を使う。

#### 3.4 BigQuery MCP の起動だけを確認する

公式の [BigQuery と MCP Toolbox の接続手順](https://docs.cloud.google.com/bigquery/docs/pre-built-tools-with-mcp-toolbox)に従い、Toolbox の BigQuery 組み込み設定を stdio で起動する。サンプルが `BIGQUERY_PROJECT` を設定するため、利用者が追加の設定ファイルを作る必要はない。

```bash
uv run \
  --env-file .env \
  python dsv4_wsl_poc_agent.py --ping-bq-mcp
```

**成功の目印:** `[OK] BigQuery MCP が起動しました` に続いて `list_table_ids` と `execute_sql` が表示される。この段階では DeepSeek も SQL も実行しない。

#### 3.5 DeepSeek から MCP 経由で実テーブルを確認する

次のコマンドでは、Azure 上の DeepSeek が MCP Toolbox の `list_table_ids` でテーブルを確認し、`execute_sql` で 5 行だけ読み取る。バッククォートの直前にある `\` は、WSL のシェルが SQL の一部をコマンドとして誤実行しないために必要。

```bash
uv run \
  --env-file .env \
  python dsv4_wsl_poc_agent.py \
  --bigquery-mcp \
  --prompt "MCP Toolbox の list_table_ids で project=${BQ_PROJECT}、dataset=${BQ_DATASET} に ${BQ_TABLE} が存在することを確認してください。次に execute_sql で SELECT * FROM \`${BQ_PROJECT}.${BQ_DATASET}.${BQ_TABLE}\` LIMIT 5 を実行してください。行の値は表示せず、使用した MCP ツール名、テーブルの存在、SQL の成否、取得行数だけを回答してください。"
```

**成功の目印:** `Tool #1: list_table_ids`、`Tool #2: execute_sql` に続き、テーブルが存在すること、SQL 成功、取得行数 5 が表示される。

**動作確認（2026-09-12）:** Toolbox v1.11.0 で、DeepSeek → MCP Toolbox → BigQuery の順に `list_table_ids` と `execute_sql` が成功済み。Akira（AIエージェント）が自律運営しているサイト[LLM Data Hub](https://llm.okamomedia.tokyo/) のSearch Consoleデータにアクセス。

5 行確認結果を報告します。

- **使用した MCP ツール名**: `list_table_ids` / `execute_sql`
- **テーブルの存在**: `okamo1-153103.searchconsole_llm.searchdata_url_impression` は存在します
- **SQL の成否**: 成功
- **取得行数**: 5 行

exit=0

> **重要:** `--prebuilt bigquery` は Toolbox が build-time 用途として提供する設定で、信頼できない利用者へ公開する本番 API 用ではない。また `execute_sql` は更新 SQL も受け取り得るため、プロンプトだけに頼らず、SA には `roles/bigquery.jobUser` と対象データセットの `roles/bigquery.dataViewer` だけを付け、Data Editor などの書き込み権限を付けない。

#### 3.6 サンプルコードの簡単な読み方

`--bigquery-mcp` を付けた場合は、次の順番で処理する。

```text
main()
  -> Azure / GCP の設定確認
  -> _build_bigquery_mcp()
  -> toolbox --prebuilt bigquery --stdio
  -> _run_agent() が DeepSeek に MCP ツールを渡す
  -> DeepSeek が list_table_ids / execute_sql を呼ぶ
  -> MCP Toolbox が BigQuery を読み取る
```

| コード | 役割 |
|---|---|
| `main()` | コマンドライン引数を読み、診断または通常実行を選ぶ |
| `_setup_gcp_sa()` | `xxx.json` の場所を確認し、Google Cloud の認証環境変数を設定する |
| `_build_model()` | Azure 上の DeepSeek を Chat Completions 方式で使うモデルを作る |
| `_build_bigquery_mcp()` | `toolbox --prebuilt bigquery --stdio` を子プロセスとして起動する |
| `ping_bigquery_mcp()` | MCP ツール一覧だけを確認する。DeepSeek と SQL は実行しない |
| `BIGQUERY_MCP_TOOL_NAMES` | DeepSeek に渡す BigQuery MCP ツールをメタデータ取得と SQL 実行の 5 個に限定する |
| `_run_agent()` | DeepSeek に MCP ツールを渡し、モデルからのツール呼び出しを実行する |

`--ping-bq` は SDK 直結の障害切り分け、`--ping-bq-mcp` は MCP 起動だけの確認、`--bigquery-mcp` は DeepSeek から MCP を実際に使う確認である。3 段階を混同しない。

#### 3.7 AI エージェントでレポートを作成する

Windows から見つけやすい保存先を先に決める。WSL では Windows の C ドライブが `/mnt/c/` に見える。

```bash
export WINDOWS_REPORT_DIR="/mnt/c/DeepSeekV4PoC/reports"
mkdir -p "$WINDOWS_REPORT_DIR"
```

`WINDOWS_REPORT_DIR` を省略した場合も、サンプルは同じ場所を既定のコピー先として使う。

```bash
uv run \
  --env-file .env \
  python dsv4_wsl_poc_agent.py \
  --bigquery-mcp
```

Word ファイルの作成とグラフ（`write_chart_png`）に必要なライブラリは、0 章の `uv add` で追加済み。`No module named 'docx'` が出る場合は、`uv add python-docx` が済んでいるか確認する。

サンプルは次の順で動く。

1. MCP の `execute_sql` で BigQuery に `SELECT 1` を実行する。
2. MCP の `list_dataset_ids` で、閲覧できるデータセットを最大 8 件取得する。
3. `write_work_report` で `作業レポート.docx` を作り、C ドライブへコピーする。
4. `cleanup_work_files` で一時ファイルを削除し、Word ファイルだけ残す。

**成功の目印:** 最終応答に `windows_explorer_path` として `C:\DeepSeekV4PoC\reports\作業レポート.docx` が表示される。次のコマンドで Windows のエクスプローラーを開く。

```bash
explorer.exe "$(wslpath -w "$WINDOWS_REPORT_DIR")"
```

開いたフォルダーで `作業レポート.docx` をダブルクリックする。WSL 側の原本は `generated_files/dsv4_wsl_poc/作業レポート.docx` にも残る。

任意の依頼を試す場合は `--prompt` を使う。ただし、PoC では個人情報や機密情報を入力しない。

`--prompt` を自分で書くときは、先頭に `日本語で回答してください。` を付ける。既定の `DEFAULT_PROMPT` には日本語の指示が入っているが、`--prompt` で置き換えると指示が消えるため、付けないと**モデルが中国語で回答することがある**。

```bash
uv run \
  --env-file .env \
  python dsv4_wsl_poc_agent.py \
  --bigquery-mcp \
  --prompt "日本語で回答してください。BigQuery の接続を確認し、見えるデータセット名を最大3件報告して"
```

---

### 4. 応用例: 在庫切れアラート・発注予測レポート

第3章で確認した DeepSeek と MCP を、日々の業務へ当てはめる例を示す。ここでは社内の在庫データが SQL Server にあるものとし、毎朝、在庫切れが近い商品と推奨発注量を Word レポートにまとめる。

```text
SQL Server の在庫集計ビュー
  -> MCP Toolbox の読み取りツール
  -> Azure 上の DeepSeek が結果を整理
  -> write_work_report が Word を作成
  -> /mnt/c/DeepSeekV4PoC/reports/ へコピー
  -> Windows のエクスプローラーからダブルクリック
```

この例が自動化するのは **発注候補の抽出とレポート作成まで**。仕入先への注文登録やメール送信は行わない。実発注は担当者がレポートを確認して承認する。

#### 4.1 毎日動かす場合の価格メリット

1 回あたり入力 10 万・出力 2 万トークンという同一の利用量を両モデルに当てはめ、2026-09 時点の公開単価で大まかな価格比を比べる。実際の請求額を示す厳密な見積もりではない。

| モデル | 相対的なモデル料金の目安 | 見方 |
|---|---:|---|
| Azure Foundry DeepSeek-V4 Flash Global | **1** | 比較の基準 |
| Claude Sonnet 5（参考） | **約 14** | 同じトークン数なら DeepSeek の約 14 倍 |

つまり、この前提では **DeepSeek V4 Flash は Claude Sonnet 5 より 90% 以上安い水準**になる。単発の相談だけでなく、毎日の定型レポートを継続して実行しやすいことが、この応用例での利点。

ただし、これは **モデルのトークン料金だけを比べた参考値**であり、両モデルの品質が同等という意味ではない。契約、リージョン、割引、モデルごとのトークンの数え方によって比率も変わる。MCP のツール定義と検索結果も入力トークンに含まれ、Azure リソース、DB、ネットワーク、保存、監視、人の確認作業の費用は別途かかる。実運用前に実測トークン数と Azure Cost Management で再計算する。最新単価の確認先は [Azure Foundry の DeepSeek 料金](https://azure.microsoft.com/en-us/pricing/details/ai-foundry-models/deepseek/) と [Anthropic API 料金](https://platform.claude.com/docs/en/about-claude/pricing)。

#### 4.2 SQL Server を読み取り元として追加する

SQL Server はこの応用例の読み取り元として、ここから追加する。BigQuery の動作確認だけを行う場合、この設定は不要。

自社の SQL Server を用意できない場合は、別紙 [Azure SQL 無料枠で在庫サンプルを用意する](docs/20260912_Azure%20SQL%20無料枠で在庫サンプルを用意する.md) を先に実施する。4.3 以降は、その別紙で作る `dbo.InventoryOrderView` を前提にした説明を含む。

BigQuery では第3章の組み込み設定を使った。SQL Serverでも同じ [MCP Toolbox for Databases](https://github.com/googleapis/mcp-toolbox) を使う。サンプルはToolbox v1.11.0の公式組み込み設定 `--prebuilt mssql` を利用するため、利用者が `tools.yaml` などの設定ファイルを作る必要はない。接続値は5つの `MSSQL_*` 環境変数から渡し、Python に `pyodbc` や ODBC ドライバを直接追加しない。

`--prebuilt mssql` が公開するツールは、SQLを実行する `execute_sql` とテーブルを確認する `list_tables` の2つ。サンプルもこの2つだけをDeepSeekへ渡す。

> **重要:** `execute_sql` は、技術的には更新 SQL も受け取れる。プロンプトの指示だけでは更新を完全に防げないため、DB 管理者に **SELECT だけ許可した読み取り専用 SQL Server ユーザー**を発行してもらう。本番用途では、SQL 文を固定できる `mssql-sql` などを別途設計する。

##### 4.2.1 Toolbox のインストールを確認する

第3.3節でインストールした Toolbox をそのまま使う。

```bash
export PATH="$HOME/.local/bin:$PATH"
toolbox --version
```

コマンドが見つからない場合は、第3.3節に戻ってインストールする。

##### 4.2.2 SQL Server の接続情報を `.env` に追記する

値は DB 管理者から受け取る。パスワードは画面に残さないよう、非表示入力にして `.env` へ書き込む。

```bash
read -rsp "SQL Server password: " MSSQL_PASSWORD && echo

cat >> .env <<EOF

# SQL Server（第4章で使う読み取り専用ユーザー）
MSSQL_HOST="<SQL_SERVER_HOST>"
MSSQL_PORT="1433"
MSSQL_DATABASE="<DATABASE_NAME>"
MSSQL_USER="<READ_ONLY_USER>"
MSSQL_PASSWORD="$MSSQL_PASSWORD"
EOF

chmod 600 .env
unset MSSQL_PASSWORD
grep -c . .env   # 行数が増えたことを確認する（値は表示しない）
```

`MSSQL_*` も他の値と同様に `.env` にまとめる。`.env` は [.gitignore](.gitignore) の対象で、第7章で削除する。会社のルールでパスワードをファイルに残せない場合は、`.env` に書かず、その都度 `export` してもよい（`--env-file .env` と併用できる）。

**別紙の Azure SQL を使う場合は、この節は実施済み。** そのまま 4.2.3 へ進む。

`<...>` が残っていたら値を置き換える。会社の SQL Server は、通常インターネット用プロキシではなく社内ネットワークや VPN 経由で接続する。必要な経路はネットワーク管理者へ確認する。

まず TCP ポートへ到達できるか確認する。この確認では SQL Server にログインしない。

```bash
set -a; . ./.env; set +a

python3 -c 'import os,socket; socket.create_connection((os.environ["MSSQL_HOST"], int(os.environ["MSSQL_PORT"])), timeout=5).close(); print("tcp_ok")'
```

**成功の目印:** `tcp_ok`。失敗した場合は、ホスト名、ポート、VPN、ファイアウォールを確認する。

##### 4.2.3 Toolbox の起動だけを確認する

```bash
uv run \
  --env-file .env \
  python dsv4_wsl_poc_agent.py \
  --ping-toolbox
```

**成功の目印:** `[OK] Toolbox が起動しました: tools=2`。`execute_sql` と `list_tables` の定義を取得するが、この段階では SQL はまだ実行しない。Toolboxは起動時にSQL Serverへ接続するため、ホスト、ポート、VPN、認証情報が正しくない場合はここで失敗する。

##### 4.2.4 SQL Server へ `SELECT 1` を実行する

Azure AI の設定は必要だが、`--sql-server-only` を付けるため GCP の設定は不要で、GCP 用ツールや鍵も読み込まない。

```bash
uv run \
  --env-file .env \
  python dsv4_wsl_poc_agent.py \
  --sql-server-only \
  --prompt "日本語で回答してください。SQL Server の execute_sql で SELECT 1 AS ok を実行し、結果だけを報告して"
```

**成功の目印:** `ok` の値として `1` が返る。接続に失敗した場合は、次の順番で確認する。

1. `tcp_ok` が出るか。
2. ユーザー名、パスワード、データベース名が正しいか。
3. SQL Server ユーザーにログイン権限と `SELECT` 権限があるか。
4. `.env` に `MSSQL_HOST`、`MSSQL_PORT`、`MSSQL_DATABASE`、`MSSQL_USER`、`MSSQL_PASSWORD` の 5 つが入っているか（`grep -c '^MSSQL' .env` が 5 以上）。

#### 4.3 在庫レポート用のデータを準備する

SQL Server への接続を確認できたら、レポートで読むビューと業務ルールを決める。

##### 4.3.1 先に準備するもの

**この資料のサンプル（別紙で作る構成）**は次のとおり。自社の SQL Server を使う場合は、この表を DB 管理者・業務担当者と合わせて読み替える。

| 種類 | 名前 | 内容 |
|---|---|---|
| 表 | `dbo.Inventory` | 在庫の元データ 12 商品。`ProductCode`、`ProductName`、`AvailableStock`、`AvgDailySales`、`InboundQty`、`InboundDate`、`SafetyStockDays`、`LeadTimeDays`、`OrderLot`、`DataAsOf` |
| ビュー | `dbo.InventoryOrderView` | 1 商品 1 行の判定結果。`PredictedStockAtArrival`、`RecommendedOrderQty`、`Priority`（1=緊急、2=要確認、3=通常）、`AlertReason` |
| ユーザー | `dsv4_readonly` | 上のビューへの `SELECT` だけ。表への更新権限は付けない |

DB 管理者と業務担当者に準備してもらう内容は次のとおり。

| 準備するもの | 内容 |
|---|---|
| 読み取り用ビュー | 在庫・売上・入荷予定を結合し、1 商品 1 行にしたビュー（サンプルは `dbo.InventoryOrderView`） |
| 読み取り専用ユーザー | 上のビューへの `SELECT` だけを許可。商品、在庫、発注テーブルへの更新権限は付けない |
| 業務ルール | 平均販売数の対象期間、安全在庫日数、調達リードタイム、発注ロット、対象外商品の条件 |
| 実行時刻 | 例: 毎朝の在庫連携が完了した後。データ更新前に実行しない |
| 保存・通知方法 | Word ファイルの保存先と、担当者へ知らせる方法。通知処理は別途用意する |

ビューには、少なくとも次の列を持たせる。括弧内はサンプルの列名で、実際の列名は DB 管理者と合わせる。

| 列の役割 | 内容 | サンプルの列名 |
|---|---|---|
| 商品識別 | 商品コード、商品名 | `ProductCode` / `ProductName` |
| 現在庫 | 手持在庫、引当済み在庫、販売可能在庫 | `AvailableStock` |
| 需要 | 過去の販売実績から計算済みの 1 日平均販売数 | `AvgDailySales` |
| 入荷予定 | 発注済み数量、最短入荷予定日 | `InboundQty` / `InboundDate` |
| 発注条件 | 安全在庫、リードタイム、発注ロット | `SafetyStockDays` / `LeadTimeDays` / `OrderLot` |
| 判定結果 | 入荷時点の予測在庫、推奨発注量、アラート理由、データ基準日時 | `PredictedStockAtArrival` / `RecommendedOrderQty` / `AlertReason` / `DataAsOf` |

予測式や丸め規則は DeepSeek に推測させず、SQL ビュー側で計算する。これにより、担当者が同じ入力に対して同じ判定結果を確認できる。

##### 4.3.2 サンプルのどこを変えるか

| 変更箇所 | 変更内容 | 変えないもの |
|---|---|---|
| `DEFAULT_PROMPT` | BigQuery の確認手順を、在庫候補の抽出、件数集計、Word レポート作成へ置き換える | Azure DeepSeek のモデル生成処理 |
| `SYSTEM_PROMPT` | 在庫判定を推測しない、SQL Server では `SELECT` / `WITH` だけ、行の欠損を隠さない、という業務ルールを追加する | 秘密を出力しないルール |
| `write_work_report` の呼び出し | `data_source` と `filename` を在庫レポート用に指定する | Word を作成する関数本体 |

最初の試行では Python を書き換えず、`--prompt` で業務プロンプトを渡せる。動作が固まったら、同じ内容を `DEFAULT_PROMPT` に移す。`--prompt` の具体例は 4.4 にある。`dbo.InventoryOrderView` と列名の部分を、自社のビュー名と列名に読み替える。

#### 4.4 在庫レポートを作成する

SQL Server では件数制限に `LIMIT` ではなく `TOP` を使う。実際の SQL は、ビューの列名に合わせて DB 管理者が確認する。

まず、C ドライブ上のコピー先を設定する。

```bash
export WINDOWS_REPORT_DIR="/mnt/c/DeepSeekV4PoC/reports"
mkdir -p "$WINDOWS_REPORT_DIR"
```

続けて、在庫レポートを作成する。

```bash
uv run \
  --env-file .env \
  python dsv4_wsl_poc_agent.py \
  --sql-server-only \
  --prompt "日本語で回答してください。SQL Server の execute_sql だけを使ってください。dbo.InventoryOrderView から推奨発注量が 0 より大きい商品を優先度順に最大100件取得し、対象件数、緊急件数、データ基準日時、商品コード、商品名、販売可能在庫、入荷時点の予測在庫、推奨発注量、アラート理由をまとめてください。値や列がない場合は推測せず不足項目として記載してください。write_work_report の data_source は SQL Server (MCP Toolbox / read-only)、filename は 在庫切れアラート発注予測レポート.docx とし、表を含む Word ファイルを作成してください。SQL は SELECT または WITH だけを使い、発注登録やデータ更新はしないでください。"
```

`--sql-server-only` により、GCP の鍵、BigQuery、GCS のツールは読み込まれない。`write_work_report` は WSL に原本を保存した後、`WINDOWS_REPORT_DIR` に同じ Word ファイルをコピーする。

プロンプトの `dbo.InventoryOrderView` と列名は、自社のビュー名・列名に読み替える。

#### 4.5 Windows からレポートを開く

`write_work_report` の結果には、WSL の原本、C ドライブ上のコピー、Windows 表記の 3 つのパスが返る。

```json
{
  "wsl_path": "generated_files/dsv4_wsl_poc/在庫切れアラート発注予測レポート.docx",
  "windows_path": "/mnt/c/DeepSeekV4PoC/reports/在庫切れアラート発注予測レポート.docx",
  "windows_explorer_path": "C:\\DeepSeekV4PoC\\reports\\在庫切れアラート発注予測レポート.docx"
}
```

WSL で次を実行すると、Windows のエクスプローラーで保存先フォルダーが開く。

```bash
explorer.exe "$(wslpath -w "$WINDOWS_REPORT_DIR")"
```

`C:\DeepSeekV4PoC\reports` が開いたら、`在庫切れアラート発注予測レポート.docx` をダブルクリックする。WSL 内の深いフォルダーを Windows から探したり、手作業でファイルを移したりする必要はない。

#### 4.6 出来上がるレポートと日次運用

| セクション | 記載内容 |
|---|---|
| サマリー | 発注候補件数、緊急件数、データ基準日時 |
| 優先一覧 | 商品、販売可能在庫、予測在庫、推奨発注量、理由 |
| 要確認事項 | 入荷日未定、販売実績不足、マスタ欠損など |
| 前提 | 集計期間、安全在庫、リードタイム、発注ロット |
| 承認欄 | 発注担当者が確認した結果。サンプル自身は発注しない |

定時実行にする場合は、このコマンドを Windows タスク スケジューラ、cron、Azure Container Apps Job などから起動する。サンプル単体にはスケジュール機能と通知機能はないため、運用環境に合わせて別途追加する。日次化する前に、実測トークン数、失敗時の通知、ファイルの保存期間、担当者の承認手順も決める。

---

### 5. 活用を広げるヒント

#### 5.1 Oracle も接続先の一例

MCP Toolbox は **Oracle にも対応している**。そのため、SQL Server を Oracle に置き換えても、基本構成は同じ。

```text
Oracle の業務用ビュー
  -> Oracle の読み取り専用ユーザー
  -> MCP Toolbox
  -> Azure 上の DeepSeek が結果を要約
  -> Word レポートを C ドライブへコピー
  -> 担当者が Windows から確認
```

このチュートリアル用サンプルにはOracle接続を組み込まない。実際に接続するときは [Oracle Source の公式資料](https://mcp-toolbox.dev/integrations/oracle/source/) を確認し、DB 管理者と別のサンプルおよび接続手順を作成する。Oracle の場合も、更新権限を持たないユーザーと、業務用に列や計算式を整理した読み取り専用ビューから始める。

#### 5.2 AIに任せると楽なユースケース案

AIが特に役立つのは、**毎回ほぼ同じデータを集め、担当者が増減や注意点を探して文章にまとめている仕事**。接続先はOracleに限らない。MCPやAPIで読み取れるデータであれば、Web担当、営業、サポート、管理部門などの日次・週次レポートにも同じ構成を使える。

最も想像しやすい例は、Web担当者が毎週作るGA4とGoogle Search Console（GSC）のレポート。

```text
GA4 MCP: ページ別の訪問数、流入元、コンバージョン
  + GSC MCP: 検索語句、クリック数、表示回数、CTR、平均掲載順位
  -> Azure上のDeepSeekが前週と比較し、変化が大きいページを整理
  -> コメントと次に確認する項目を含む週次レポートの下書きを作成
  -> Web担当者が数値と表現を確認して共有
```

例えば「検索表示は増えたのに訪問が減ったページ」や「訪問は増えたのにコンバージョンが減ったページ」を毎週探し、定型文へ転記する作業をAIに任せられる。AIは原因を断定せず、「タイトル変更の影響を確認する」「フォームの動作を確認する」といった**調査候補**として記載し、最終判断は担当者が行う。

| よくある業務とデータ元 | 作るレポート | AIに任せると楽なこと | 人またはデータ取得側で確定すること |
|---|---|---|---|
| Web運用（GA4 MCP + GSC MCP） | アクセス・検索流入の週次レポート | 前週比で変化が大きいページを抽出し、要点、調査候補、コメント案をまとめる | 集計期間、指標、コンバージョン定義、公開前の内容確認 |
| 問い合わせ対応（チケット・FAQシステム） | 問い合わせ傾向とFAQ候補 | 似た問い合わせを分類し、頻出テーマ、代表例、FAQの下書きをまとめる | 正確な件数、緊急度、個人情報の除外、回答内容の承認 |
| 営業管理（CRM・SQL Serverなど） | 停滞案件と次回確認事項の週次一覧 | 担当者・商品別に状況を要約し、確認漏れの候補を整理する | 金額、商談段階、停滞日数、顧客への連絡判断 |
| 社内文書（SharePointなど） | 規程・手順書の更新ダイジェスト | 変更点を利用部門別に言い換え、周知文の下書きを作る | 正式版、施行日、閲覧権限、法務・管理部門の承認 |
| 基幹業務（Oracleの一例） | 支払期限超過、仕入価格上昇、納期遅延の確認一覧 | 影響が大きい候補を並べ、部門別の要約と確認順を作る | 金額、期限、差額、遅延日数、取引状態を読み取り専用ビューで計算 |

どの例でも、AIを数値の計算元にはしない。件数、金額、期間比較、判定条件はMCPツールのSQLや各サービスの集計結果で確定し、DeepSeekには**確定した結果の並べ替え、要約、文章の下書き**を任せる。更新、公開、顧客への連絡、会計処理などは自動実行せず、人が確認して承認する。

この資料のGA4 MCPとGSC MCPは、活用方法を理解するための構成例であり、特定のMCPサーバーを推奨したり、接続を動作確認したりしたものではない。

GA4やGSCなどで外部のMCPサーバーを利用する場合は、導入前に提供元、認証方式、データの送信先、利用できるツールを情報システム部門が確認する。認証には読み取りに必要な最小権限だけを付与し、サイト設定やデータを変更できるツールはDeepSeekへ渡さない。

#### 5.3 活用を広げる進め方

| 段階 | 実施内容 | 完了の目安 |
|---|---|---|
| 1. 小さな PoC | 1 つの読み取り専用ビュー、1 つの質問、手動実行で試す | 元データと Word の件数・金額が一致する |
| 2. 定型レポート化 | プロンプトと出力項目を固定し、日次または週次で実行する | 担当者が同じ観点で継続確認できる |
| 3. 通知を追加 | 完成ファイルの場所と処理結果を、承認済みの通知手段で知らせる | 失敗時も担当者が気付ける |
| 4. 対象業務を追加 | 売上、債権、購買などを 1 テーマずつ追加する | 各テーマにデータ責任者と確認手順がある |

複数業務を最初から一つのエージェントへ詰め込まず、**1 ビュー・1 レポート・1 担当部署**から始める。各段階で、読み取り権限、個人情報や機密情報の範囲、SQL 実行時間、トークン使用量、レポートの保存期間、最終承認者を確認してから対象を広げる。

---

### 6. やってはいけないこと

- API キー、サービスアカウントの JSON 鍵、プロキシパスワード、SQL Serverのパスワードを Git、チャット、レポート本文に記載する。
- Foundry DeepSeek を `OpenAIResponsesModel` で呼ぶ。
- 「Azure だから日本閉じ」と顧客に説明する。
- GlobalStandard なのに「データは米国（または日本）だけ」と説明する。
- エージェントに **UPDATE/DELETE 可能な SQL** を渡す。
- 公式 DeepSeek（中国）キーと Azure キーを取り違える。
- PoC のサービスアカウントに `roles/editor` や `predefinedRoles/admin` を付ける。

---

### 7. チュートリアル環境を後片付けする

WSL を削除するだけでは、Google Cloud 上の鍵、サービスアカウント、IAM 設定、Azure 上のリソースは削除されない。**最初にクラウド側を後片付けし、その後でローカル認証情報または WSL を削除する。**

削除はすべて任意。この章は「このチュートリアルで作ったものを全部消す」場合の手順で、順番は次のとおり。

| 順番 | 節 | 対象 |
|---:|---|---|
| 1 | 7.1 | 削除対象の確認（GCP と Azure） |
| 2 | 7.2 | GCP: IAM・鍵・使い捨てサービスアカウント |
| 3 | 7.3 | Azure: AI リソース（と、別紙で作った Azure SQL） |
| 4 | 7.4 | ローカルの認証情報（WSL を残して使う場合だけ） |
| 5 | 7.5 | WSL ごと削除（任意） |

#### 7.1 削除対象を確認する

第2章から同じターミナルを使っている場合は、次の確認だけを行う。

```bash
printf 'SA_PROJECT=%s\nBQ_PROJECT=%s\nBQ_DATASET=%s\nSA_EMAIL=%s\nKEY_JSON=%s\n' \
  "$SA_PROJECT" "$BQ_PROJECT" "$BQ_DATASET" "$SA_EMAIL" "$KEY_JSON"
```

ターミナルを開き直した場合は、`.env` をシェルへ読み込む。`gcloud` と `bq` は `.env` を直接読まないため。秘密鍵の内容は表示しない。

```bash
set -a; . ./.env; set +a

printf 'SA_PROJECT=%s\nBQ_PROJECT=%s\nBQ_DATASET=%s\nSA_EMAIL=%s\nKEY_JSON=%s\n' \
  "$SA_PROJECT" "$BQ_PROJECT" "$BQ_DATASET" "$SA_EMAIL" "$KEY_JSON"
```

`.env` を削除してしまった場合は、`xxx.json` から SA の公開情報を読み戻す。`BQ_PROJECT` と `BQ_DATASET` は控えておいた値を使う。

```bash
export KEY_JSON="$PWD/xxx.json"
export SA_EMAIL="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["client_email"])' "$KEY_JSON")"
export SA_PROJECT="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["project_id"])' "$KEY_JSON")"
export BQ_PROJECT="<BIGQUERY_DATA_PROJECT_ID>"
export BQ_DATASET="<DATASET_ID>"
```

`SA_EMAIL` が `deepseek-poc-` で始まり、プロジェクトとデータセットが第2章で使った値と一致することを確認する。既存SAや別環境を誤って削除しないため、一つでも違う場合は削除を中止する。

Azure 側も確認する。**第1部で自分が `az group create` して作ったリソースグループであること**を確かめる。既存の業務用リソースグループを使った場合は、7.3 でリソースグループを削除せず、AI リソースだけを削除する。

```bash
set -a; . ./.env; set +a

az group show -n "$AZURE_RG" --query "{name:name,location:location}" -o table
az resource list -g "$AZURE_RG" --query "[].{name:name,type:type}" -o table
```

**確認の目印:** `AZURE_RG` の一覧に、AI リソース（`Microsoft.CognitiveServices/accounts`）と、このチュートリアルで作ったものだけが表示される。他部門のリソースや本番リソースが入っている場合は、7.3 でリソースグループを削除しない。

#### 7.2 GCP の IAM・鍵・サービスアカウントを削除する

最初に、データセットの Data Viewer とプロジェクトの Job User を解除する。

```bash
bq query --use_legacy_sql=false --project_id="$BQ_PROJECT" \
  "REVOKE \`roles/bigquery.dataViewer\` ON SCHEMA \`${BQ_PROJECT}.${BQ_DATASET}\` FROM \"serviceAccount:${SA_EMAIL}\";"

gcloud projects remove-iam-policy-binding "$BQ_PROJECT" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/bigquery.jobUser" \
  --quiet
```

続けて、`xxx.json` から鍵IDを読み取り、Google Cloud 上の鍵を削除する。鍵IDは秘密鍵本体ではないが、画面や作業報告書へ転記する必要はない。

```bash
export KEY_ID="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["private_key_id"])' "$KEY_JSON")"

gcloud iam service-accounts keys delete "$KEY_ID" \
  --iam-account="$SA_EMAIL" \
  --project="$SA_PROJECT" \
  --quiet
```

最後に、使い捨てSAとWSL上のJSON鍵を削除する。

```bash
gcloud iam service-accounts delete "$SA_EMAIL" \
  --project="$SA_PROJECT" \
  --quiet

rm -f "$KEY_JSON"
test ! -e "$KEY_JSON" && echo "[OK] ローカルの JSON 鍵を削除しました"
```

各コマンドが成功したことを確認してから次へ進む。権限不足で `REVOKE` または IAM 解除に失敗した場合は無視せず、`SA_EMAIL`、`BQ_PROJECT`、`BQ_DATASET` を Google Cloud 管理者へ伝えて解除を依頼する。第2.4節で有効化した API は他の処理でも利用される可能性があるため、この手順では無効化しない。

#### 7.3 Azure のリソースを削除する

第1部で作った Azure AI（DeepSeek）のリソースを削除する。リソースグループごと削除すると、その中の AI リソースとモデル デプロイも一緒に消える。**7.1 で確認したとおり、第1部で自分が作ったリソースグループである場合だけ**実施する。

```bash
set -a; . ./.env; set +a

# 消える対象を最後に確認する（AI リソースだけであること）
az resource list -g "$AZURE_RG" --query "[].{name:name,type:type}" -o table

az group delete -n "$AZURE_RG" --yes --no-wait
echo "[OK] リソースグループ ${AZURE_RG} を削除中（AI リソースとモデル デプロイが消える）"
```

既存の業務用リソースグループを使った場合は、リソースグループを削除せず、AI リソースだけを削除する。

```bash
set -a; . ./.env; set +a

az cognitiveservices account delete -g "$AZURE_RG" -n "$AZURE_AI_ACCOUNT"
```

- モデル デプロイと、そのレート制限のクォータは、AI リソースを削除すると解放される。
- 削除の反映には数分かかることがある。確認する場合:

```bash
az group list --query "[?name=='$AZURE_RG'].name" -o tsv
az cognitiveservices account list --query "[?name=='$AZURE_AI_ACCOUNT'].name" -o tsv
```

別紙「Azure SQL 無料枠で在庫サンプルを用意する」で Azure SQL を作った場合は、続けて別紙の「後片付け」を実施する。リソースグループ `rg-dsv4-sqlpoc` ごと削除する手順で、`.env` の `SQL_RG` を使う。**7.4 で `.env` を削除する前に実施する。**

#### 7.4 ローカルの認証情報を削除する（WSL を残す場合だけ）

WSLを今後も使う場合は、クラウド操作がすべて終わった後に Azure CLI と `gcloud` からログアウトし、環境変数を解除する。

```bash
az logout
az account clear

ACTIVE_GCLOUD_ACCOUNT="$(gcloud config get-value account 2>/dev/null)"
if [[ -n "$ACTIVE_GCLOUD_ACCOUNT" && "$ACTIVE_GCLOUD_ACCOUNT" != "(unset)" ]]; then
  gcloud auth revoke "$ACTIVE_GCLOUD_ACCOUNT" --quiet
fi

unset AZURE_AI_ENDPOINT AZURE_AI_API_KEY AZURE_AI_DEPLOYMENT AZURE_RG AZURE_AI_ACCOUNT
unset GOOGLE_APPLICATION_CREDENTIALS GOOGLE_BIGQUERY_PROJECT GOOGLE_BIGQUERY_LOCATION
unset SA_PROJECT BQ_PROJECT BQ_DATASET BQ_TABLE SA_ID SA_EMAIL KEY_JSON KEY_ID
unset MSSQL_HOST MSSQL_PORT MSSQL_DATABASE MSSQL_USER MSSQL_PASSWORD

# .env には API キーが残っているため、ファイルごと削除する
rm -f .env
test ! -e .env && echo "[OK] .env を削除しました"
```

WSL側のレポートも不要なら削除する。

```bash
rm -rf generated_files/dsv4_wsl_poc
```

`/mnt/c/DeepSeekV4PoC/reports` はWindows側のファイルなので、この操作では削除されない。レポートに業務データが含まれる場合は、保存期間のルールに従ってWindows側でも削除する。

#### 7.5 WSL を削除する（WSL ごと消す場合・任意）

今回の PoC 専用に WSL ディストリビューションを用意し、今後使わない場合だけ実施する。`wsl --unregister` は、そのディストリビューション内のリポジトリ、認証情報、ツール、設定、ファイルをすべて復元できない形で削除する。他の作業にも同じ Ubuntu を使っている場合は実施しない。

先に 7.2 と 7.3 を完了し、必要なファイルを Windows 側へ退避してから Ubuntu を閉じる。WSL ごと削除する場合は、7.4（ローカルの認証情報の削除）は実施しなくてよい（ディストリビューションと一緒に消えるため）。続いて **Windows PowerShell** で実際のディストリビューション名を確認する。

```powershell
wsl --list --verbose
```

一覧に表示された名前が `Ubuntu-24.04` であることを確認してから削除する。名前が違う場合は、以下の `Ubuntu-24.04` を表示された名前へ置き換える。

```powershell
wsl --terminate Ubuntu-24.04
wsl --unregister Ubuntu-24.04
wsl --list --verbose
```

最後の一覧から対象名が消えていれば完了。これにより WSL 内の Azure CLI、`gcloud`、JSON 鍵、ログインキャッシュは消えるが、次のものは消えない。

- Google Cloud 上の SA、鍵、IAM 設定。7.2 で先に削除する。
- Azure 上の AI リソース。7.3 で先に削除する（既存のリソースグループを使った場合は AI リソースだけを削除する）。
- `/mnt/c/`、つまり Windows の C ドライブへコピーしたレポート。

---

### 8. 作業完了チェックリスト

- [ ] 第1部の `--ping-llm` で `llm_response=2` を確認した
- [ ] `gcloud` をインストールし、`gcloud auth login` を完了した
- [ ] SA に Job User と Data Viewer を必要最小限の範囲で付与した
- [ ] `xxx.json` を `.gitignore` 対象へ配置し、`chmod 600` を実行した
- [ ] 0 章で `.env` を作成し、`chmod 600` を実行した（API キーを含むため Git へ登録しない）
- [ ] 0 章で `uv add google-cloud-bigquery python-docx matplotlib` を実行した
- [ ] `--check-config` でローカル設定の `[OK]` を確認した
- [ ] `--ping-bq` の結果に `"ok": 1` がある
- [ ] `toolbox --version` で導入済みの Toolbox を確認した
- [ ] `--ping-bq-mcp` で `list_table_ids` と `execute_sql` を確認した
- [ ] `--bigquery-mcp` で DeepSeek からテーブル一覧と `SELECT ... LIMIT 5` を実行した
- [ ] Word レポートが `/mnt/c/DeepSeekV4PoC/reports/` にコピーされ、Windows から開けた
- [ ] SQL Server を使う場合だけ、読み取り専用ユーザー、環境変数、`--ping-toolbox`、`SELECT 1` を確認した
- [ ] GA4・GSCのWebレポートやOracleの業務レポートでも、読み取り専用と人の承認が必要であることを確認した
- [ ] Data Viewer と Job User を解除した
- [ ] Google Cloud 上のJSON鍵と使い捨てSAを削除した
- [ ] WSL上の `xxx.json` を削除し、CLIからログアウトした（またはPoC専用WSLを削除した）
- [ ] `.env` を削除した（API キーが残るため）
- [ ] Azure のリソースグループ（第1部で作ったもの）または AI リソースを削除した
- [ ] 別紙で Azure SQL を作った場合、リソースグループを削除した

---

### 9. 参考リンク

- 別紙: [Azure SQL 無料枠で在庫サンプルを用意する](docs/20260912_Azure%20SQL%20無料枠で在庫サンプルを用意する.md)
- Azure 料金（DeepSeek）: https://azure.microsoft.com/en-us/pricing/details/ai-foundry-models/deepseek/
- Anthropic API 料金（Claude Sonnet 比較用）: https://platform.claude.com/docs/en/about-claude/pricing
- gcloud インストール（Debian/Ubuntu）: https://docs.cloud.google.com/sdk/docs/install#deb
- SA 作成: https://docs.cloud.google.com/iam/docs/service-accounts-create
- SA 鍵: https://docs.cloud.google.com/iam/docs/keys-create-delete
- SA 削除: https://docs.cloud.google.com/iam/docs/service-accounts-delete-undelete
- BigQuery IAM: https://docs.cloud.google.com/bigquery/docs/access-control
- BigQuery と MCP Toolbox: https://docs.cloud.google.com/bigquery/docs/pre-built-tools-with-mcp-toolbox
- MCP Toolbox: https://github.com/googleapis/mcp-toolbox
- Toolbox SQL Server ソース: https://mcp-toolbox.dev/integrations/mssql/source/
- Toolbox SQL Server execute-sql: https://mcp-toolbox.dev/integrations/mssql/tools/mssql-execute-sql/
- Toolbox SQL Server組み込み設定: https://mcp-toolbox.dev/integrations/mssql/prebuilt-configs/microsoft-sql-server/
- Toolbox Oracle ソース: https://mcp-toolbox.dev/integrations/oracle/source/
- WSLディストリビューションの登録解除: https://learn.microsoft.com/windows/wsl/basic-commands#unregister-or-uninstall-a-linux-distribution
