# Appdata — Git Tracking Strategy

This directory holds persistent data for all Docker services. The `.gitignore` uses a 4-layer approach to track configuration files while excluding bulk data.

## Layer 1: Exclude Data-Heavy Directories

Most service directories are excluded entirely — they contain databases, caches, media libraries, or other large data.

```gitignore
audiobookshelf/
postgres/
redis/
radarr/
sonarr/
```

## Layer 2: Include Config-Only Directories

Directories that contain only configuration (no large data) are included in full.

```gitignore
!authentik/
!nginx-*/
!smtp-relay/
```

## Layer 3: Selectively Include Configs

Specific config subdirectories or file patterns are pulled back in from otherwise-excluded services.

```gitignore
!nextcloud/config/
!nextcloud/config/**
!jdownloader/cfg/
!jdownloader/cfg/**
!*/config.xml
!*/*.conf
```

## Layer 4: Re-Exclude Sensitive/Data From Included Dirs

```gitignore
authentik/media/
authentik/certs/
nginx-*/logs/
```

## Adding a New Service

1. **Generates lots of data** (databases, caches, media): Add `servicename/` to Layer 1 exclusions
2. **Want to track its configs**: Add selective includes in Layer 3:
   ```gitignore
   !servicename/config/
   !servicename/config/**
   ```
3. **Has logs or sensitive data in tracked dirs**: Add specific exclusions in Layer 4

**Pattern:** Exclude by default, explicitly include only what should be version controlled.
