# Run the lab on AWS EC2 (Singapore)

`lab-ec2.yaml` is a CloudFormation template that creates one always-on EC2
instance in `ap-southeast-1`, installs Docker and starts the lab on first boot.
The template rejects any other region.

**What is reachable from the internet:** only TCP **8443**, over HTTPS, and
only the path `POST /webhook/support-agent`. Every other path returns 404. The
n8n editor, the mocks and SSH are not exposed. You manage the instance through
AWS Systems Manager Session Manager.

## What it creates

| Resource | Why |
| --- | --- |
| VPC, public subnet, internet gateway, route table | Keeps the lab apart from your other workloads |
| Security group | Inbound 8443 from `AllowedCidr` only. Outbound 80/443 for updates and images |
| EC2 instance (Amazon Linux 2023, `t3.medium` by default) | Runs the lab. IMDSv2 is required and the 20 GB gp3 disk is encrypted |
| Elastic IP | A fixed public address that survives stop and start |
| IAM role (`AmazonSSMManagedInstanceCore` only) | Session Manager shell and port forwarding, no SSH keys |

On first boot, `bootstrap.sh` installs Docker, Compose and automatic security
updates. It then runs `setup.sh` to generate random keys, makes a self-signed
certificate for the Elastic IP, and runs
`docker compose -f docker-compose.yml -f docker-compose.public.yml up -d --build`.
The containers restart on their own after a reboot.

**Rough cost:** about USD 45 a month always on, for a `t3.medium`, the Elastic IP
and a 20 GB disk at Singapore on-demand prices. Check the current AWS pricing pages.

## Deploy

You need the AWS CLI v2 with credentials that can create the resources above,
including IAM (hence `CAPABILITY_IAM`).

```sh
aws cloudformation deploy \
  --region ap-southeast-1 \
  --stack-name n8n-agent-lab \
  --template-file deploy/aws/lab-ec2.yaml \
  --capabilities CAPABILITY_IAM \
  --parameter-overrides RepoBranch=main AllowedCidr=0.0.0.0/0

aws cloudformation describe-stacks --region ap-southeast-1 --stack-name n8n-agent-lab \
  --query "Stacks[0].Outputs" --output table
```

Until the lab PR is merged, deploy the PR branch with
`RepoBranch=claude/secured-n8n-agent-lab`. To use the console instead, open
CloudFormation in Singapore, choose **Create stack**, upload `lab-ec2.yaml`,
and tick the IAM acknowledgement.

The stack finishes in a few minutes, but the lab needs about 5 more minutes to
install and start. Progress is logged to `/var/log/lab-bootstrap.log` on the instance.

## Use it

Get the portal key from the instance. It is generated there and never leaves it:

```sh
aws ssm start-session --region ap-southeast-1 --target <InstanceId>
sudo cat /opt/lab/.env          # PORTAL_WEBHOOK_KEY=...
sudo tail /var/log/lab-bootstrap.log
```

Call the webhook from anywhere. `-k` is needed because the certificate is self-signed:

```sh
curl -k -X POST https://<ElasticIp>:8443/webhook/support-agent \
  -H "Content-Type: application/json" \
  -H "X-Portal-Key: <PORTAL_WEBHOOK_KEY>" \
  -H "X-Customer-Session: sess-priya-demo" \
  -d '{"message": "where is ORD-5001"}'
```

To skip `-k`, copy `/opt/lab/certs/lab.crt` to your machine and use `--cacert lab.crt`.

On the instance, `cd /opt/lab && sudo ./tests/smoke-test.sh` runs all 11 checks.

### n8n editor

The editor is not on the internet. Forward it to your machine with the
[Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html):

```sh
aws ssm start-session --region ap-southeast-1 --target <InstanceId> \
  --document-name AWS-StartPortForwardingSession \
  --parameters portNumber=8080,localPortNumber=8080
```

Then open <http://localhost:8080> and create the owner account. Do this soon
after deploying, because n8n gives the owner role to whoever sets it up first,
and only someone who can open a tunnel can reach that page.

## Update or remove

- **Pull new lab code:** in a Session Manager shell, run
  `cd /opt/lab && sudo git pull && sudo docker compose -f docker-compose.yml -f docker-compose.public.yml up -d --build`.
- **Rotate keys:** delete `/opt/lab/.env`, run `sudo ./setup.sh`, then run
  `sudo docker compose -f docker-compose.yml -f docker-compose.public.yml down -v`
  and `up -d` again. This wipes n8n data, because the credentials are re-imported with the new keys.
- **Tear down everything:**
  `aws cloudformation delete-stack --region ap-southeast-1 --stack-name n8n-agent-lab`.

## Security notes for an always-on public lab

- The portal key is the only thing protecting the webhook, because the demo
  session tokens are in this repository. Treat the key as a secret, rotate it if
  it leaks, and narrow `AllowedCidr` when you know who will call the lab.
- The webhook is rate-limited to 30 requests per minute per client IP, with a
  burst of 10, and bodies are capped at 16 KB.
- The certificate is self-signed. For a trusted certificate, point a domain at the
  Elastic IP and replace `certs/lab.crt` and `certs/lab.key` with a Let's Encrypt
  pair, or put an AWS load balancer with an ACM certificate in front.
- The data is fake and the LLM is a mock, so nothing real is at risk. If you
  connect a real model or real data, review the "Not covered here" section of
  `docs/CONTROLS.md` first.
- Consider turning on VPC Flow Logs and CloudWatch alarms if the lab will stay
  up for a long time.
