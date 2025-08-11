#!/bin/bash
# Generic Postfix configuration script to disable incoming mail
# Works on any system by modifying existing configuration safely

set -euo pipefail

POSTFIX_CONFIG="/etc/postfix/main.cf"
BACKUP_SUFFIX=".docker-mail-backup.$(date +%Y%m%d-%H%M%S)"

echo "Configuring Postfix to disable incoming mail and prevent bounce-backs..."

# Check if Postfix is installed
if [[ ! -f "$POSTFIX_CONFIG" ]]; then
    echo "Postfix not installed or configuration not found at $POSTFIX_CONFIG"
    echo "Skipping Postfix configuration."
    exit 0
fi

# Backup original configuration
echo "Creating backup: ${POSTFIX_CONFIG}${BACKUP_SUFFIX}"
sudo cp "$POSTFIX_CONFIG" "${POSTFIX_CONFIG}${BACKUP_SUFFIX}"

# Function to safely update or add a configuration parameter
update_postfix_param() {
    local param="$1"
    local value="$2"
    local comment="$3"
    
    if grep -q "^${param}[[:space:]]*=" "$POSTFIX_CONFIG"; then
        # Parameter exists, update it
        echo "Updating existing parameter: $param"
        sudo sed -i "s/^${param}[[:space:]]*=.*/${param} = ${value}/" "$POSTFIX_CONFIG"
    else
        # Parameter doesn't exist, add it
        echo "Adding new parameter: $param"
        echo "" | sudo tee -a "$POSTFIX_CONFIG" >/dev/null
        echo "# $comment" | sudo tee -a "$POSTFIX_CONFIG" >/dev/null
        echo "$param = $value" | sudo tee -a "$POSTFIX_CONFIG" >/dev/null
    fi
}

# Function to comment out existing parameter
comment_postfix_param() {
    local param="$1"
    
    if grep -q "^${param}[[:space:]]*=" "$POSTFIX_CONFIG"; then
        echo "Commenting out parameter: $param"
        sudo sed -i "s/^${param}[[:space:]]*=/#&/" "$POSTFIX_CONFIG"
    fi
}

echo "Modifying Postfix configuration..."

# 1. Restrict mydestination to only localhost
# First, comment out any existing mydestination
comment_postfix_param "mydestination"
# Then add our restrictive version
update_postfix_param "mydestination" "localhost.local, localhost" "Restrict to localhost only - all mail handled by Docker"

# 2. Restrict mynetworks to localhost only
update_postfix_param "mynetworks" "127.0.0.0/8" "Allow only localhost connections"

# 3. Set interfaces to loopback only
update_postfix_param "inet_interfaces" "loopback-only" "Only listen on loopback interface"

# 4. Add bounce prevention
update_postfix_param "smtpd_reject_unlisted_recipient" "yes" "Prevent bounce-backs for unlisted recipients"

# 5. Clear relayhost to prevent external relay attempts
update_postfix_param "relayhost" "" "No external relay - Docker handles all mail"

echo "Configuration changes applied successfully."

# Verify the changes
echo ""
echo "Verification - checking key parameters:"
grep -E "^(mydestination|mynetworks|inet_interfaces|smtpd_reject_unlisted_recipient|relayhost)" "$POSTFIX_CONFIG" || true

echo ""
echo "Postfix configuration updated. Key changes:"
echo "- mydestination: restricted to localhost only"
echo "- mynetworks: restricted to 127.0.0.0/8"  
echo "- inet_interfaces: set to loopback-only"
echo "- smtpd_reject_unlisted_recipient: enabled to prevent bounces"
echo "- relayhost: cleared (Docker handles all mail)"
echo ""
echo "Backup saved as: ${POSTFIX_CONFIG}${BACKUP_SUFFIX}"

# Note about restarting
echo ""
echo "Note: Postfix service should be stopped and disabled when using Docker mail system."
echo "The mail-setup.sh script will handle this automatically."