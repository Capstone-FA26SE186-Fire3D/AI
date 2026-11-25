# Cap nhat AI (rag-api) len EC2 (xem docs/deploy-aws.md). Chay tu thu muc goc cua repo AI:
#   powershell -ExecutionPolicy Bypass -File deploy\aws\update-ai.ps1
# Lay code dang co trong <repo>\rag-api (nho git pull truoc). Env production (KHONG nam trong repo) doc tu
# $env:FIRE3D_AI_ENV, mac dinh la rag-api-server.env o thu muc chua repo (vi du C:\do an\rag-api-server.env).
$ErrorActionPreference = "Stop"
$Ip     = "56.10.105.247"
$Domain = "56-10-105-247.sslip.io"   # doi khi chuyen sang ai.fet3d.io.vn
$Key    = if ($env:FIRE3D_SSH_KEY) { $env:FIRE3D_SSH_KEY } else { "$env:USERPROFILE\Downloads\fire3d-be.pem" }
$Repo   = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Env    = if ($env:FIRE3D_AI_ENV) { $env:FIRE3D_AI_ENV } else { Join-Path (Split-Path $Repo -Parent) "rag-api-server.env" }
$Zip    = Join-Path $env:TEMP "rag-api-deploy.zip"
if (-not (Test-Path $Env)) { throw "Thieu file env production: $Env (dat FIRE3D_AI_ENV neu de cho khac)" }

Write-Host "== 1/3 Nen code"
Remove-Item $Zip -ErrorAction SilentlyContinue
tar -a -c -f $Zip --exclude=__pycache__ -C (Join-Path $Repo "rag-api") app contracts requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Nen zip that bai" }

Write-Host "== 2/3 Gui len server"
# setup-ai.sh doc ~/rag-api-deploy.zip va ~/rag-api-server.env, nen giu dung ten file khi chep len.
scp -i $Key $Zip "ubuntu@${Ip}:~/rag-api-deploy.zip"
if ($LASTEXITCODE -ne 0) { throw "scp that bai" }
scp -i $Key (Join-Path $PSScriptRoot "setup-ai.sh") $Env "ubuntu@${Ip}:~"
if ($LASTEXITCODE -ne 0) { throw "scp that bai" }
if ((Split-Path $Env -Leaf) -ne "rag-api-server.env") {
  ssh -i $Key "ubuntu@$Ip" "mv ~/$(Split-Path $Env -Leaf) ~/rag-api-server.env"
}
Remove-Item $Zip -ErrorAction SilentlyContinue

Write-Host "== 3/3 Cai dat va khoi dong lai"
# Xoa ban env va goi nen khoi thu muc home sau khi cai, du thanh cong hay loi.
ssh -i $Key "ubuntu@$Ip" "sudo bash setup-ai.sh $Domain; rc=`$?; rm -f ~/rag-api-server.env ~/rag-api-deploy.zip; exit `$rc"
if ($LASTEXITCODE -ne 0) { throw "setup-ai.sh that bai" }

Write-Host "Kiem tra tu ben ngoai:"
curl.exe -s "https://$Domain/ready"
