# Deploying the Coffee Price Analyzer on AWS EC2

The app is one container (FastAPI + SQLite + a background poller). The database lives in a Docker volume, so
rebuilds and updates keep your data and settings.

> **Important:** the app has no login of its own, and anyone who can reach it can change your conversion settings.
> Never open port 8100 to the internet. The setups below put HTTPS and a password in front of it (Caddy), or keep it
> private behind an SSH tunnel.

## Quick start: free tier, almost hands-off (recommended)

You do four things; the instance does the rest on its own. It installs Docker, builds the app, gets an HTTPS
certificate, generates a login, restarts itself after any reboot, and updates itself nightly from GitHub.
No SSH, domain or command line on the server is needed.

> Tested: the Docker image builds and runs healthy on a laptop, and the scripts pass syntax checks. The full
> run on a real EC2 instance has not been tested, so if something differs, the troubleshooting notes at the bottom
> and the setup log (step 4) will show why.

**1. Put the code on GitHub** (once). Create an empty repository named `price-analyzer` on github.com. Public is the
simplest: there are no secrets in the code (the database and `.env` are git-ignored). Then, in the `price-analyzer` folder:

```bash
git init -b main
git add .
git commit -m "Coffee price analyzer"
git remote add origin https://github.com/YOUR-USER/price-analyzer.git
git push -u origin main
```

**2. Edit one line.** Open `deploy/user-data.sh` and set `REPO_URL` to your repository's URL (and push that change).

**3. Launch the instance.** AWS console, **EC2 → Launch instance**:

- **AMI:** Ubuntu Server 24.04 LTS
- **Instance type:** the one marked **Free tier eligible** (usually `t2.micro` or `t3.micro`)
- **Key pair:** *Proceed without a key pair* is fine. You can create one later if you want SSH access.
- **Network settings:** allow **HTTPS (443)** and **HTTP (80)** from anywhere. Leave SSH off, or allow it from *My IP* only.
- **Advanced details → User data:** paste the whole of `deploy/user-data.sh`.
- Launch.

**4. Wait about 5–10 minutes**, then read your address and login: select the instance → **Actions → Monitor and
troubleshoot → Get system log**, and scroll to the bottom:

```
 PRICE ANALYZER READY
 Address : https://3-250-10-20.sslip.io
 Login   : admin / <generated password>
```

Open the address and sign in. Your browser may need a minute while the certificate is issued. The first page load
fetches the sales history, which takes another minute.

**What you get without doing anything else**

- Checks the exchange every 30 minutes and the news every 12 hours, around the clock.
- Starts by itself after a reboot, and your data is kept in a Docker volume.
- Pulls the latest code from GitHub every night at 03:30 UTC (06:30 Nairobi time) and rebuilds if it changed.
  To ship a change, just `git push`. To update right now: connect and run `sudo /opt/price-analyzer/deploy/update.sh`.

**Two things to know**

- **The address changes if the instance is stopped and started** (it gets a new public IP). The app re-points itself
  at boot, but your bookmark breaks. To keep one address, allocate an **Elastic IP** (EC2 → Elastic IPs → Allocate →
  Associate with the instance) *before* you rely on the address, then reboot the instance once. AWS bills for public
  IPv4 addresses by the hour, and the free offer covers a limited amount, so check **Billing → Free tier** in your account.
  The free tier itself has changed over time (a 12-month trial on older accounts, a credit-based plan on newer ones),
  so confirm what your account includes before leaving it running.
- **The free `*.sslip.io` name is a shared public service.** If a certificate is ever refused, use your own domain:
  create an A record to the Elastic IP, set `CUSTOM_DOMAIN="prices.yourdomain.com"` in `user-data.sh`, and launch again.

**Change the password later** (needs SSH): run `sudo docker run --rm caddy:2 caddy hash-password --plaintext 'new'`,
paste the result into `BASIC_AUTH_HASH='...'` in `/opt/price-analyzer/.env`, then `sudo systemctl restart price-analyzer`.

**Delete everything:** terminate the instance and release the Elastic IP (if you made one).

---

# Manual alternatives

Prefer to control each step, or to use SSH, an SSH tunnel, or Amazon Linux? Use the steps below instead. There are two
ways to reach the app:

| | Access | Needs a domain | Good for |
|---|---|---|---|
| **A. SSH tunnel** (default) | `http://localhost:8100` on your computer, through SSH | No | Just you, simplest and safest |
| **B. HTTPS + login** | `https://prices.yourdomain.com` | Yes | Sharing with colleagues or opening it on a phone |

## 1. Launch the instance

In the AWS console, **EC2 → Launch instance**:

1. **Name:** `price-analyzer`
2. **AMI:** Ubuntu Server 24.04 LTS (Amazon Linux 2023 also works). Default login user is `ubuntu`
   (`ec2-user` on Amazon Linux).
3. **Instance type:** `t3.micro` (or `t4g.micro` for ARM). 1 GB RAM is enough. The bootstrap script adds swap for the
   image build.
4. **Key pair:** create one (RSA, `.pem`) and download it. Keep it safe.
5. **Network / security group:** create a new one with:
   - SSH (22) from **My IP** only
   - Option B only: also HTTP (80) and HTTPS (443) from anywhere (`0.0.0.0/0`)
   - Do **not** add 8100.
6. **Storage:** 8–10 GB gp3 is plenty.
7. Launch, then **Elastic IPs → Allocate → Associate** with the instance so the address survives restarts.

On Windows, if SSH complains that the key file is too open, run in Git Bash: `chmod 400 /path/to/key.pem`.

## 2. Prepare the instance (once)

From the project folder on your computer (Git Bash on Windows):

```bash
cd price-analyzer
ssh -i /path/to/key.pem ubuntu@<ELASTIC_IP> 'bash -s' < deploy/ec2-bootstrap.sh
```

This installs Docker and the compose plugin. It takes a couple of minutes.

## 3. Deploy

```bash
./deploy/deploy.sh ubuntu@<ELASTIC_IP> /path/to/key.pem
```

This uploads the code, builds the image on the server, starts the container, and waits until it reports healthy.
The first start fetches the exchange reports and the news backfill, which takes a minute or two.

**Option A: open it through an SSH tunnel**

```bash
ssh -i /path/to/key.pem -L 8100:localhost:8100 ubuntu@<ELASTIC_IP>
```

Leave that running and open http://localhost:8100.

## 4. Option B: HTTPS with a login

1. In your DNS provider, create an **A record** `prices.yourdomain.com → <ELASTIC_IP>` and wait for it to resolve.
2. On the server, create the password hash and the settings file:

   ```bash
   ssh -i /path/to/key.pem ubuntu@<ELASTIC_IP>
   cd ~/price-analyzer
   sudo docker run --rm caddy:2 caddy hash-password --plaintext 'choose-a-strong-password'
   cp .env.example .env && nano .env
   ```

   Set `DOMAIN`, `BASIC_AUTH_USER`, and paste the hash into `BASIC_AUTH_HASH` (keep the single quotes).
3. Redeploy from your computer. The script sees `DOMAIN` in the server's `.env` and starts Caddy too:

   ```bash
   ./deploy/deploy.sh ubuntu@<ELASTIC_IP> /path/to/key.pem
   ```

4. Open `https://prices.yourdomain.com`. Caddy gets the certificate automatically; the first load can take a few
   seconds. If it fails, check that ports 80 and 443 are open in the security group and that the DNS record resolves.

## 5. Day to day

All commands run on the server (`ssh -i key.pem ubuntu@<ip>`, then `cd ~/price-analyzer`):

```bash
sudo docker compose logs -f app          # watch the checks for new sales
sudo docker compose ps                   # status and health
sudo docker compose restart app
sudo docker compose down                 # stop (data is kept)
```

**Update the app:** change the code on your computer, then re-run `./deploy/deploy.sh ...`.

**New sales:** nothing to do. The app checks the exchange every 30 minutes and the news every 12 hours. You can change
this with `PA_POLL_MINUTES` and `PA_NEWS_HOURS` in the server's `.env`. When a new season starts in October,
sales are tracked per season automatically.

## 6. Backups

The only data worth keeping is your saved settings and any manual entries; the sales can be re-fetched. A backup is
still cheap:

```bash
~/price-analyzer/deploy/backup.sh     # writes ~/price-analyzer/backups/prices-<date>.db, keeps the last 14
```

Daily at 02:00, via cron (`crontab -e`):

```
0 2 * * * /home/ubuntu/price-analyzer/deploy/backup.sh >> /home/ubuntu/backup.log 2>&1
```

To also copy backups to S3, create a bucket, attach an IAM role with write access to the instance, install the AWS CLI,
and set `BACKUP_S3=s3://your-bucket/price-analyzer` in the cron line.

**Restore:** stop the app, copy a backup into the volume, start again:

```bash
sudo docker compose stop app
sudo docker compose cp backups/prices-YYYYMMDD-HHMMSS.db app:/data/prices.db
sudo docker compose start app
```

## 7. Tear down (stop paying)

```bash
sudo docker compose down -v      # on the server: removes the container AND the data volume
```

Then in the AWS console: terminate the instance, **release the Elastic IP** (an unattached one is billed), and delete
the security group and key pair if you no longer need them.

## Troubleshooting

**Quick start setup (user data)**

- **No "READY" message after 15 minutes:** the full log is in the same system log, and on the server in
  `/var/log/price-analyzer-setup.log` and `/var/log/cloud-init-output.log`. The usual cause is a wrong `REPO_URL`
  (a private repository cannot be cloned without a token; make it public).
- **Page does not load but the log says READY:** wait a minute for the certificate, and check the security group allows
  ports 80 and 443 from anywhere.
- **Browser warns about the certificate:** the address changed (instance restarted without an Elastic IP). Use the new
  address from the system log, or the instance's current public IP written with dashes plus `.sslip.io`.
- **Redo the setup from scratch:** terminate the instance and launch a new one with the same user data.

**Manual setup**

- **`permission denied` on the key:** `chmod 400 key.pem`.
- **Build killed or "out of memory":** the bootstrap adds swap on 1 GB instances. Check with `free -m`, or use a
  `t3.small`.
- **App not healthy:** `sudo docker compose logs app`. The instance needs outbound internet access to reach
  nairobicoffeeexchange.co.ke and kilimonews.co.ke (the default security group allows this).
- **Dashboard shows an error under "Last checked":** a source was briefly unreachable. It retries on the next cycle,
  or press "Check for new sale".
- **Certificate not issued (option B):** DNS must point at the Elastic IP, and ports 80/443 must be open.

## Cost note

A `t3.micro` or `t4g.micro`, an 8 GB volume and an Elastic IP attached to a running instance is a small monthly bill.
Check current pricing and your free-tier eligibility in the AWS console before launching.
