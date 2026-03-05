#!/bin/bash
# Docker-based mail system setup script
# Sets up complete mail routing through Docker smtp-relay container
# Prevents bounce-backs and ensures reliable mail delivery to Gmail

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_ROOT="$(dirname "$SCRIPT_DIR")"

echo "=== Docker Mail System Setup ==="
echo "This will configure your system to route all mail through Docker smtp-relay"
echo

# Check if running as root
if [[ $EUID -eq 0 ]]; then
    echo "ERROR: Please run this script as a regular user with sudo access"
    echo "Usage: $0"
    exit 1
fi

# Verify Docker setup
echo "1. Verifying Docker setup..."
if ! docker ps --format "table {{.Names}}" | grep -q "^smtp-relay$"; then
    echo "ERROR: smtp-relay container is not running"
    echo "Please ensure your Docker compose includes the smtp-relay service"
    exit 1
fi
echo "✓ smtp-relay container is running"

# Create logs directory
echo "2. Setting up logging..."
sudo mkdir -p "$DOCKER_ROOT/logs"
sudo touch "$DOCKER_ROOT/logs/mail.log"
sudo chmod 666 "$DOCKER_ROOT/logs/mail.log"
echo "✓ Mail logging configured"

# Backup original sendmail binaries
echo "3. Backing up original sendmail configuration..."
if [[ -f /usr/sbin/sendmail ]] && [[ ! -f /usr/sbin/sendmail.original ]]; then
    if [[ -L /usr/sbin/sendmail ]]; then
        # It's a symlink, backup the target
        sudo cp "$(readlink -f /usr/sbin/sendmail)" /usr/sbin/sendmail.original 2>/dev/null || true
        sudo mv /usr/sbin/sendmail /usr/sbin/sendmail.link.backup
    else
        # It's a regular file
        sudo mv /usr/sbin/sendmail /usr/sbin/sendmail.original
    fi
fi

if [[ -f /etc/alternatives/sendmail ]] && [[ ! -f /etc/alternatives/sendmail.original ]]; then
    if [[ -L /etc/alternatives/sendmail ]]; then
        sudo cp "$(readlink -f /etc/alternatives/sendmail)" /etc/alternatives/sendmail.original 2>/dev/null || true
        sudo mv /etc/alternatives/sendmail /etc/alternatives/sendmail.backup
    else
        sudo mv /etc/alternatives/sendmail /etc/alternatives/sendmail.original
    fi
fi
echo "✓ Original sendmail binaries backed up"

# Install our Docker-based sendmail
echo "4. Installing Docker-based sendmail system..."

# Check if sendmail-system exists, if not create from template
if [[ ! -f "$DOCKER_ROOT/bin/sendmail-system" ]]; then
    if [[ -f "$DOCKER_ROOT/config/sendmail-system-template" ]]; then
        echo "Creating sendmail-system from template..."
        
        # Prompt for email address
        read -p "Enter your Gmail address for receiving system mail: " -r USER_EMAIL
        if [[ -z "$USER_EMAIL" ]]; then
            echo "ERROR: Email address is required"
            exit 1
        fi
        
        # Create sendmail-system from template
        sed "s/YOUR_EMAIL@gmail.com/$USER_EMAIL/" "$DOCKER_ROOT/config/sendmail-system-template" > "$DOCKER_ROOT/bin/sendmail-system"
        chmod +x "$DOCKER_ROOT/bin/sendmail-system"
        echo "✓ Created sendmail-system with email: $USER_EMAIL"
    else
        echo "ERROR: Neither sendmail-system nor template found"
        exit 1
    fi
else
    echo "✓ sendmail-system already exists"
fi

sudo ln -sf "$DOCKER_ROOT/bin/sendmail-system" /usr/sbin/sendmail
sudo ln -sf "$DOCKER_ROOT/bin/sendmail-system" /etc/alternatives/sendmail
echo "✓ Docker sendmail system installed"

# Configure Postfix to prevent bounce-backs
echo "5. Configuring Postfix to prevent bounce-backs..."
if command -v postfix >/dev/null 2>&1; then
    # Use the generic Postfix configuration script
    "$DOCKER_ROOT/config/postfix-disable-incoming.sh"
    
    # Stop and disable postfix
    sudo systemctl stop postfix 2>/dev/null || true
    sudo systemctl disable postfix 2>/dev/null || true
    
    echo "✓ Postfix configured and disabled"
else
    echo "✓ Postfix not installed, skipping"
fi

# Configure cron to not send mail by default
echo "6. Configuring cron mail settings..."

# Update user crontab
if crontab -l >/dev/null 2>&1; then
    current_crontab=$(crontab -l)
    if ! echo "$current_crontab" | grep -q "^MAILTO="; then
        (echo 'MAILTO=""'; echo "$current_crontab") | crontab -
        echo "✓ Updated user crontab MAILTO setting"
    else
        echo "✓ User crontab MAILTO already configured"
    fi
else
    echo 'MAILTO=""' | crontab -
    echo "✓ Created user crontab with MAILTO setting"
fi

# Update root crontab
if sudo crontab -l >/dev/null 2>&1; then
    current_root_crontab=$(sudo crontab -l)
    if ! echo "$current_root_crontab" | grep -q "^MAILTO="; then
        temp_file=$(mktemp)
        echo 'MAILTO=""' > "$temp_file"
        echo "$current_root_crontab" >> "$temp_file"
        sudo crontab "$temp_file"
        rm "$temp_file"
        echo "✓ Updated root crontab MAILTO setting"
    else
        echo "✓ Root crontab MAILTO already configured"
    fi
else
    echo 'MAILTO=""' | sudo crontab -
    echo "✓ Created root crontab with MAILTO setting"
fi

# Create test script if it doesn't exist
echo "7. Setting up test utilities..."
if [[ ! -f "$DOCKER_ROOT/bin/test-mail" ]]; then
    cat > "$DOCKER_ROOT/bin/test-mail" << 'EOF'
#!/bin/bash
# Test script for the Docker-based mail system

set -euo pipefail

echo "Testing Docker-based mail system..."

# Test 1: Simple mail to user (should map to Gmail)
echo "Test 1: Sending mail to local user 'will'"
echo "This is a test message from the Docker mail system - Test 1" | /usr/sbin/sendmail will

# Test 2: Mail with explicit recipient  
echo "Test 2: Sending mail with explicit recipient"
echo "This is a test message from the Docker mail system - Test 2" | /usr/sbin/sendmail wemcdonald@gmail.com

# Test 3: Mail with subject and proper headers (like cron would send)
echo "Test 3: Sending mail with headers (cron-style)"
cat << INNEREOF | /usr/sbin/sendmail -t
To: will
Subject: Docker Mail Test - Cron Style
From: root@willflix.org

This is a test message that simulates what cron would send.
The system is working if you receive this in your Gmail.

Test completed at: $(date)
INNEREOF

# Test 4: Test through standard mail command
echo "Test 4: Using system mail command"
echo "This is a test using the mail command" | mail -s "Docker Mail Test - Mail Command" will

echo "All tests sent. Check your Gmail for 4 test messages."
echo "Monitor the logs with: sudo tail -f /docker/logs/mail.log"
EOF
    chmod +x "$DOCKER_ROOT/bin/test-mail"
fi
echo "✓ Test utilities ready"

# Verify the setup
echo
echo "=== Setup Verification ==="
echo "Checking mail system components..."

# Check sendmail link
if [[ -L /usr/sbin/sendmail ]] && [[ "$(readlink /usr/sbin/sendmail)" == "$DOCKER_ROOT/bin/sendmail-system" ]]; then
    echo "✓ /usr/sbin/sendmail correctly linked"
else
    echo "⚠ /usr/sbin/sendmail link may not be correct"
fi

# Check Docker container
if docker ps --format "table {{.Names}}" | grep -q "^smtp-relay$"; then
    echo "✓ smtp-relay container is running"
else
    echo "❌ smtp-relay container is not running"
fi

# Check log file
if [[ -w "$DOCKER_ROOT/logs/mail.log" ]]; then
    echo "✓ Mail log file is writable"
else
    echo "⚠ Mail log file permissions may need adjustment"
fi

echo
echo "=== Setup Complete! ==="
echo
echo "Your system is now configured to route all mail through Docker."
echo
echo "What was configured:"
echo "- System sendmail replaced with Docker-based wrapper"
echo "- All local users (will, root, etc.) map to wemcdonald@gmail.com"  
echo "- Postfix disabled to prevent bounce-backs"
echo "- Cron configured to use new mail system"
echo "- Mail logging enabled: $DOCKER_ROOT/logs/mail.log"
echo
echo "Test the system:"
echo "  $DOCKER_ROOT/bin/test-mail"
echo
echo "Monitor mail activity:"  
echo "  sudo tail -f $DOCKER_ROOT/logs/mail.log"
echo
echo "Send a quick test:"
echo "  echo 'Test message' | sendmail will"
echo