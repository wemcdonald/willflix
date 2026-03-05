#!/bin/bash
# Initialize Samba users on container startup

# Create system user if it doesn't exist
if ! id will > /dev/null 2>&1; then
    echo "Creating system user 'will'"
    adduser -D -s /bin/false will
fi

# Add Samba user if it doesn't exist
if ! pdbedit -L | grep -q "^will:"; then
    echo "Adding Samba user 'will'"
    echo -e "will\nwill" | smbpasswd -a will
    echo "Samba user 'will' added successfully"
else
    echo "Samba user 'will' already exists"
fi