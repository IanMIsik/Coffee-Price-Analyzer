# Deploying the Coffee Price Analyzer on AWS EC2

The app is one container (FastAPI + SQLite + a background poller). The database lives in a Docker volume, so
rebuilds and updates keep your data and settings.

> **Important:** the app has no login of its own, and anyone who can reach it can change your conversion settings.
> Never open port 8100 to the internet. The setups below put HTTPS and a password in front of it (Caddy), or keep it
> private behind an SSH tunnel.

## Quick start: one script (recommended)

Everything is done by **`deploy/setup.sh`**. It installs Docker if needed, asks a few questions the first time, keeps
your DuckDNS address pointed at the server, gets an HTTPS certificate, starts the app, and makes it start by itself
after a reboot. Running it again is safe: it keeps your settings and just rebuilds with the latest code.

> Tested: the Docker image builds and runs healthy on a laptop, the settings step of the script was run for real
> (first run, re-run, and fallback), and all scripts pass syntax checks. The full run on a real EC2 instance has not
> been tested, so if something differs, the troubleshooting notes at the bottom will help.

**You need:** an EC2 instance running Ubuntu 24.04 (choose the type marked *Free tier eligible*) with ports **80** and
**443** open to the internet and **22** open to your IP, plus a DuckDNS name and its token from duckdns.org.

**1. Connect and run the script** (first time):

```bash
git clone https://github.com/IanMIsik/Coffee-Price-Analyzer.git
cd Coffee-Price-Analyzer
./deploy/setup.sh
```

It asks:

| Question | Answer |
|---|---|
| DuckDNS name | e.g. `mycoffee` (or `mycoffee.duckdns.org`). Press Enter to skip and get a free `<ip>.sslip.io` address instead. |
| DuckDNS token | from the top of your duckdns.org page (typed hidden) |
| Dashboard login name | e.g. `admin` |
| Dashboard password | choose one, or press Enter to generate one (shown once at the end) |

When it finishes it prints the address, for example `https://mycoffee.duckdns.org`. Allow a minute for the HTTPS
certificate, and a minute or two for the first load to fetch the sales history.

**2. Updating later** (after you or Claude push new code):

```bash
cd ~/Coffee-Price-Analyzer
git pull
./deploy/setup.sh
```

It does not ask the questions again. To change the DuckDNS name or the password, add `--reconfigure`.

**Already ran an earlier automatic setup on this server?** The new script takes over the same containers and data
(they share the project name `price-analyzer`). If you have a leftover copy in `/opt/price-analyzer`, delete it after:
`sudo rm -rf /opt/price-analyzer`.

**What runs without you doing anything**

- The app checks the exchange for a new sale every 30 minutes and the news every 12 hours, around the clock.
  The dashboard in your browser refreshes its numbers every 5 minutes and shows a banner when a new sale appears.
- A DuckDNS updater runs every 5 minutes so the name always points at the server, even if the instance gets a new IP
  after a stop and start. That means you do not need an Elastic IP.
- The app starts after a reboot, and your data is kept in a Docker volume.
- At 03:30 UTC (06:30 Nairobi time) the server pulls the latest code from GitHub and rebuilds if it changed.

**Useful commands** (in the `Coffee-Price-Analyzer` folder):

```bash
sudo docker compose ps                  # status and health
sudo docker compose logs -f app         # watch it check for new sales
sudo ./deploy/setup.sh --reconfigure    # change the DuckDNS name or the password
```

**Alternative: a brand-new instance that sets itself up.** Paste `deploy/user-data.sh` (with your DuckDNS values filled
in at the top) into **Launch instance → Advanced details → User data**. It clones the repository and runs the same
`setup.sh`. The generated password appears in **Actions → Monitor and troubleshoot → Get system log**. Note that
user data is visible to anyone with access to the instance in your AWS account, including the DuckDNS token you put in it.

**Free tier:** AWS's free offer has changed over time (a 12-month trial on older accounts, a credit-based plan on newer
ones), and AWS bills hourly for public IPv4 addresses. Check **Billing → Free tier** to see what your account includes.

**Delete everything:** terminate the instance in the EC2 console (and release any Elastic IP you created).

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

**Quick start (setup.sh)**

- **`git clone` asks for a password:** the repository is private. Make it public on GitHub, or clone with a token.
- **Certificate error or page not loading:** DuckDNS must point at this server (`nslookup yourname.duckdns.org` should
  show the instance's public IP; check the token and name with `./deploy/duckdns-update.sh`, which prints OK or KO),
  and ports 80 and 443 must be open in the security group.
- **User-data setup did not finish:** read `/var/log/price-analyzer-setup.log` on the server.
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
