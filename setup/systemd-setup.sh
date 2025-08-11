#!/bin/bash
# Docker systemd services setup script
# Symlinks and enables all systemd services from /docker/systemd/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DOCKER_ROOT="$(dirname "$SCRIPT_DIR")"
SYSTEMD_DIR="$DOCKER_ROOT/systemd"
SYSTEM_SYSTEMD_DIR="/etc/systemd/system"

echo "=== Docker Systemd Services Setup ==="
echo "This will symlink and enable all systemd services from $SYSTEMD_DIR"
echo

# Check if running as root
if [[ $EUID -eq 0 ]]; then
    echo "ERROR: Please run this script as a regular user with sudo access"
    echo "Usage: $0"
    exit 1
fi

# Verify systemd directory exists
if [[ ! -d "$SYSTEMD_DIR" ]]; then
    echo "ERROR: Systemd directory not found: $SYSTEMD_DIR"
    exit 1
fi

# Find all service files
SERVICE_FILES=()
while IFS= read -r -d '' file; do
    SERVICE_FILES+=("$file")
done < <(find "$SYSTEMD_DIR" -name "*.service" -type f -print0)

if [[ ${#SERVICE_FILES[@]} -eq 0 ]]; then
    echo "No systemd service files found in $SYSTEMD_DIR"
    exit 1
fi

echo "Found ${#SERVICE_FILES[@]} service files:"
for service_file in "${SERVICE_FILES[@]}"; do
    service_name=$(basename "$service_file")
    echo "  - $service_name"
done
echo

# Confirm before proceeding
read -p "Do you want to proceed with linking and enabling these services? [y/N]: " -r
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Setup cancelled."
    exit 0
fi

# Process each service file
SUCCESS_COUNT=0
FAILED_SERVICES=()
ENABLED_SERVICES=()
ALREADY_LINKED=()
ALREADY_ENABLED=()

echo
echo "Processing services..."

for service_file in "${SERVICE_FILES[@]}"; do
    service_name=$(basename "$service_file")
    target_link="$SYSTEM_SYSTEMD_DIR/$service_name"
    
    echo -n "Processing $service_name... "
    
    # Check if already linked
    if [[ -L "$target_link" ]] && [[ "$(readlink -f "$target_link")" == "$service_file" ]]; then
        echo -n "(already linked) "
        ALREADY_LINKED+=("$service_name")
    else
        # Remove existing file/link if it exists
        if [[ -e "$target_link" ]]; then
            sudo rm "$target_link"
        fi
        
        # Create symlink
        if sudo ln -s "$service_file" "$target_link"; then
            echo -n "(linked) "
        else
            echo "FAILED to link"
            FAILED_SERVICES+=("$service_name")
            continue
        fi
    fi
    
    # Reload systemd daemon
    sudo systemctl daemon-reload
    
    # Check if already enabled
    if systemctl is-enabled "$service_name" >/dev/null 2>&1; then
        echo "(already enabled)"
        ALREADY_ENABLED+=("$service_name")
    else
        # Enable the service
        if sudo systemctl enable "$service_name"; then
            echo "(enabled)"
            ENABLED_SERVICES+=("$service_name")
        else
            echo "FAILED to enable"
            FAILED_SERVICES+=("$service_name")
            continue
        fi
    fi
    
    ((SUCCESS_COUNT++))
done

# Final daemon reload
sudo systemctl daemon-reload

echo
echo "=== Setup Summary ==="
echo "Total services processed: ${#SERVICE_FILES[@]}"
echo "Successfully configured: $SUCCESS_COUNT"

if [[ ${#ALREADY_LINKED[@]} -gt 0 ]]; then
    echo
    echo "Already linked (${#ALREADY_LINKED[@]}):"
    for service in "${ALREADY_LINKED[@]}"; do
        echo "  ✓ $service"
    done
fi

if [[ ${#ENABLED_SERVICES[@]} -gt 0 ]]; then
    echo
    echo "Newly enabled (${#ENABLED_SERVICES[@]}):"
    for service in "${ENABLED_SERVICES[@]}"; do
        echo "  ✅ $service"
    done
fi

if [[ ${#ALREADY_ENABLED[@]} -gt 0 ]]; then
    echo
    echo "Already enabled (${#ALREADY_ENABLED[@]}):"
    for service in "${ALREADY_ENABLED[@]}"; do
        echo "  ✓ $service"
    done
fi

if [[ ${#FAILED_SERVICES[@]} -gt 0 ]]; then
    echo
    echo "Failed services (${#FAILED_SERVICES[@]}):"
    for service in "${FAILED_SERVICES[@]}"; do
        echo "  ❌ $service"
    done
fi

echo
echo "=== Next Steps ==="
echo
echo "Services are now linked and enabled but NOT started."
echo "To start services, use:"
echo "  sudo systemctl start <service-name>"
echo
echo "To start all services:"
for service_file in "${SERVICE_FILES[@]}"; do
    service_name=$(basename "$service_file" .service)
    echo "  sudo systemctl start $service_name"
done
echo
echo "To check service status:"
echo "  sudo systemctl status <service-name>"
echo
echo "To view all Docker services:"
echo "  systemctl list-units '*docker*' --all"
echo
echo "To view enabled services:"
echo "  systemctl list-unit-files --state=enabled | grep docker"
echo

# Check for common issues
echo "=== Health Check ==="

# Check if Docker is running
if systemctl is-active docker >/dev/null 2>&1; then
    echo "✓ Docker service is running"
else
    echo "⚠ Docker service is not running - services may fail to start"
fi

# Check if Docker compose is available
if command -v docker-compose >/dev/null 2>&1 || docker compose version >/dev/null 2>&1; then
    echo "✓ Docker Compose is available"
else
    echo "⚠ Docker Compose not found - some services may require it"
fi

# Check for potential conflicts
echo
echo "Note: These systemd services should be used instead of 'docker compose up'"
echo "They provide better integration with system startup and management."

if [[ ${#FAILED_SERVICES[@]} -eq 0 ]]; then
    echo
    echo "🎉 All services configured successfully!"
else
    echo
    echo "⚠ Some services failed - check the logs above for details"
    exit 1
fi