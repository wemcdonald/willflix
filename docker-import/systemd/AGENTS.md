# Systemd — Service Unit Files

Every Docker Compose service gets a corresponding systemd unit file here. Currently ~36 unit files.

## Unit File Template

```ini
[Unit]
Description={Service Name}
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=true
WorkingDirectory=/docker/config
ExecStart=/usr/bin/docker compose up -d {service}
ExecStop=/usr/bin/docker compose down {service}
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

## Multi-Container Services

List all containers in both ExecStart and ExecStop:

```ini
ExecStart=/usr/bin/docker compose up -d authentik-server authentik-worker
ExecStop=/usr/bin/docker compose down authentik-server authentik-worker
```

The unit file is still named after the logical service (e.g., `authentik.service`).

## Enable Procedure

```bash
# 1. Create unit file at /docker/systemd/{service}.service

# 2. Symlink into systemd
cd /etc/systemd/system
sudo ln -s /docker/systemd/{service}.service .

# 3. Reload and enable
sudo systemctl daemon-reload
sudo systemctl enable {service}
sudo systemctl start {service}
```

Or run `/docker/setup/systemd-setup.sh` to batch-process all unit files.

## Management Commands

```bash
# Preferred — uses systemd
sudo systemctl start {service}
sudo systemctl stop {service}
sudo systemctl restart {service}
sudo systemctl status {service}
sudo journalctl -u {service} -f        # Follow logs

# Direct docker compose (always from /docker/config)
docker compose up -d {service}          # ALWAYS specify service name
docker compose down {service}           # ALWAYS specify service name
docker compose logs -f {service}
docker compose ps {service}
```
