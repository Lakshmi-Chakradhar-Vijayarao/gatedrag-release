#!/usr/bin/env bash
# Launch ONE GPU instance for a gatedrag measuring run, with a hard cost cap.
#   Dry run (default): prints the plan, quota and estimated cost; launches nothing.
#   Launch:            MAX_HOURS=6 KEY_NAME=my-key ./scripts/aws_launch_ec2.sh --yes
# The instance powers itself off after MAX_HOURS (shutdown behaviour = terminate), so a
# forgotten instance cannot keep billing. Requires a non-zero "Running On-Demand G and VT
# instances" quota in the region (new accounts start at 0: request it in Service Quotas).
set -euo pipefail
REGION="${REGION:-us-east-2}"
INSTANCE_TYPE="${INSTANCE_TYPE:-g6.xlarge}"          # 1x NVIDIA L4 24 GB, 4 vCPU, 16 GiB
MAX_HOURS="${MAX_HOURS:-6}"
KEY_NAME="${KEY_NAME:-}"
AMI_PARAM=/aws/service/deeplearning/ami/x86_64/base-oss-nvidia-driver-gpu-ubuntu-22.04/latest/ami-id

AMI=$(aws ssm get-parameter --region "$REGION" --name "$AMI_PARAM" --query Parameter.Value --output text)
QUOTA=$(aws service-quotas list-service-quotas --region "$REGION" --service-code ec2 \
  --query "Quotas[?QuotaName=='Running On-Demand G and VT instances'].Value" --output text)
PRICE=$(aws pricing get-products --region us-east-1 --service-code AmazonEC2 --filters \
  "Type=TERM_MATCH,Field=instanceType,Value=$INSTANCE_TYPE" "Type=TERM_MATCH,Field=regionCode,Value=$REGION" \
  "Type=TERM_MATCH,Field=operatingSystem,Value=Linux" "Type=TERM_MATCH,Field=tenancy,Value=Shared" \
  "Type=TERM_MATCH,Field=preInstalledSw,Value=NA" "Type=TERM_MATCH,Field=capacitystatus,Value=Used" \
  --query 'PriceList[0]' --output text | python3 -c "import sys,json;d=json.loads(sys.stdin.read());print(list(list(d['terms']['OnDemand'].values())[0]['priceDimensions'].values())[0]['pricePerUnit']['USD'])")
CAP=$(python3 -c "print(round(float('$PRICE')*$MAX_HOURS,2))")

echo "region=$REGION type=$INSTANCE_TYPE ami=$AMI"
echo "G/VT on-demand vCPU quota: $QUOTA   on-demand price: \$$PRICE/h   cost cap: \$$CAP (${MAX_HOURS}h, then auto-terminate; EBS extra)"
if [[ "${1:-}" != "--yes" ]]; then echo "DRY RUN: nothing launched. Re-run with --yes to launch."; exit 0; fi
python3 -c "import sys; sys.exit(0 if float('$QUOTA' or 0) >= 4 else 1)" || { echo "quota too low ($QUOTA vCPU): request an increase first"; exit 1; }
[[ -n "$KEY_NAME" ]] || { echo "set KEY_NAME to an existing EC2 key pair"; exit 1; }

USER_DATA=$(cat <<UD
#!/bin/bash
shutdown -h +$((MAX_HOURS*60))
UD
)
aws ec2 run-instances --region "$REGION" --image-id "$AMI" --instance-type "$INSTANCE_TYPE" --key-name "$KEY_NAME" \
  --instance-initiated-shutdown-behavior terminate --user-data "$USER_DATA" \
  --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=150,VolumeType=gp3,DeleteOnTermination=true}' \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=gatedrag-measure},{Key=AutoTerminateHours,Value=$MAX_HOURS}]" \
  --query 'Instances[0].InstanceId' --output text
echo "Next: copy the repo + data/ to the instance (scp), then: docker compose -f docker/docker-compose.gpu.yml --env-file .env up -d"
