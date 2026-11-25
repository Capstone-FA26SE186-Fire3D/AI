# Cap nhat AI (rag-api) len EC2. Chay trong PowerShell:  powershell -ExecutionPolicy Bypass -File "C:\do an\update-ai.ps1"
# Lay code dang co trong C:\do an\ai\rag-api (nho git pull truoc) va env trong C:\do an\rag-api-server.env.
$ErrorActionPreference = "Stop"
$Ip     = "56.10.105.247"
$Domain = "56-10-105-247.sslip.io"   # doi khi chuyen sang ai.fet3d.io.vn
$Key    = "$env:USERPROFILE\Downloads\fire3d-be.pem"   # fire3d-ai.pem da mat; may AI nhan key nay qua user data
$Root   = "C:\do an"

Write-Host "== 1/3 Nen code"
Remove-Item "$Root\rag-api-deploy.zip" -ErrorAction SilentlyContinue
tar -a -c -f "$Root\rag-api-deploy.zip" --exclude=__pycache__ -C "$Root\ai\rag-api" app contracts requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Nen zip that bai" }

Write-Host "== 2/3 Gui len server"
scp -i $Key "$Root\rag-api-deploy.zip" "$Root\setup-ai.sh" "$Root\rag-api-server.env" "ubuntu@${Ip}:~"
if ($LASTEXITCODE -ne 0) { throw "scp that bai" }

Write-Host "== 3/3 Cai dat va khoi dong lai"
ssh -i $Key "ubuntu@$Ip" "sudo bash setup-ai.sh $Domain; rc=`$?; rm -f ~/rag-api-server.env ~/rag-api-deploy.zip; exit `$rc"
if ($LASTEXITCODE -ne 0) { throw "setup-ai.sh that bai" }

Write-Host "Kiem tra tu ben ngoai:"
curl.exe -s "https://$Domain/ready"
