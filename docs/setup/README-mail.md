# Docker-Based Mail System

Complete mail routing system that sends all system mail through Docker smtp-relay container to Gmail.

## Features

- **Reliable Delivery**: All mail routed through proven Docker smtp-relay container
- **No Bounce-backs**: Prevents Gmail from bouncing mail back to your server
- **Local User Mapping**: Automatically maps local users (will, root) to Gmail
- **Comprehensive Logging**: Full mail activity logging to `/docker/logs/mail.log`
- **Cron Integration**: Works seamlessly with cron jobs and system services
- **Easy Testing**: Built-in test utilities for verification

## Quick Setup

```bash
# Run the automated setup script
/docker/setup/mail-setup.sh
```

## Manual Setup Steps

If you need to set up manually or understand what the script does:

1. **Prerequisites**: Ensure smtp-relay container is running in your Docker compose
2. **Install System**: Run `/docker/setup/mail-setup.sh`
3. **Test Setup**: Run `/willflix/bin/test-mail`
4. **Monitor**: `sudo tail -f /docker/logs/mail.log`

## Architecture

```
System Services (cron, smartd, etc.)
         ↓
    sendmail command
         ↓
  /willflix/bin/sendmail-system
         ↓
    smtp-relay container
         ↓
      Gmail SMTP
         ↓
   your-email@gmail.com
```

## Configuration

The setup script will prompt for your Gmail address during installation.

### User Mapping
All local users map to your specified Gmail address:
- `will` → `your-email@gmail.com`
- `root` → `your-email@gmail.com`  
- `postmaster` → `your-email@gmail.com`
- All other users → `your-email@gmail.com`

### Key Files
- `/willflix/docker/sendmail-system-template` - Template for sendmail wrapper
- `/willflix/bin/sendmail-system` - Main sendmail wrapper (created from template)
- `/willflix/docker/postfix-disable-incoming.sh` - Generic Postfix configuration script
- `/docker/logs/mail.log` - Mail activity log
- `/willflix/bin/test-mail` - Test utility
- `/docker/setup/mail-setup.sh` - Setup script

## Testing

```bash
# Run comprehensive tests
/willflix/bin/test-mail

# Quick test
echo "Test message" | sendmail will

# Monitor logs
sudo tail -f /docker/logs/mail.log
```

## Troubleshooting

### Common Issues

1. **Permission denied on log file**
   ```bash
   sudo chmod 666 /docker/logs/mail.log
   ```

2. **smtp-relay container not running**
   ```bash
   docker compose up -d smtp-relay
   ```

3. **Still getting bounce-backs**
   - Verify Postfix is stopped: `sudo systemctl status postfix`
   - Check DNS: Remove MX records for willflix.org if present

### Log Analysis
```bash
# View recent mail activity
sudo tail -20 /docker/logs/mail.log

# Search for errors
sudo grep ERROR /docker/logs/mail.log

# Monitor in real-time
sudo tail -f /docker/logs/mail.log
```

## Reverting Changes

If you need to revert to the original system:

```bash
# Restore original sendmail
sudo mv /usr/sbin/sendmail.original /usr/sbin/sendmail
sudo mv /etc/alternatives/sendmail.original /etc/alternatives/sendmail

# Re-enable Postfix
sudo systemctl enable postfix
sudo systemctl start postfix

# Restore Postfix config
sudo cp /etc/postfix/main.cf.backup.* /etc/postfix/main.cf
```

## How It Works

1. **System Integration**: Replaces system sendmail with Docker-aware wrapper
2. **Argument Processing**: Handles all standard sendmail flags and arguments
3. **User Mapping**: Maps local users to Gmail addresses automatically
4. **SMTP Relay**: Sends mail through Docker smtp-relay container
5. **Logging**: Records all mail activity for monitoring and troubleshooting
6. **Bounce Prevention**: Disables incoming mail to prevent Gmail bounce-backs