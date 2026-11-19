"""
Configuration and settings for Context-Aware Screenshots.
"""
import os
import sys
from pathlib import Path

# Friendly names mapping for common applications
FRIENDLY_APP_NAMES = {
    # Browsers
    'chrome.exe': 'Chrome',
    'brave.exe': 'Brave',
    'msedge.exe': 'Edge',
    'firefox.exe': 'Firefox',
    'opera.exe': 'Opera',

    # Developer & Productivity
    'code.exe': 'VS Code',
    'devenv.exe': 'Visual Studio',
    'antigravity ide.exe': 'Antigravity IDE',
    'windowsterminal.exe': 'Terminal',
    'cmd.exe': 'Command Prompt',
    'powershell.exe': 'PowerShell',
    'pwsh.exe': 'PowerShell',
    'postman.exe': 'Postman',
    'notion.exe': 'Notion',
    'obsidian.exe': 'Obsidian',
    'figma.exe': 'Figma',

    # Communication & Media
    'discord.exe': 'Discord',
    'spotify.exe': 'Spotify',
    'slack.exe': 'Slack',
    'telegram.exe': 'Telegram',
    'whatsapp.exe': 'WhatsApp',

    # Microsoft Office & System
    'explorer.exe': 'Explorer',
    'winword.exe': 'Word',
    'excel.exe': 'Excel',
    'powerpnt.exe': 'PowerPoint',
    'acrobat.exe': 'Acrobat Reader',

    # Games & Launchers
    'genshinimpact.exe': 'Genshin Impact',
    'yuanshen.exe': 'Genshin Impact',
    'honkaistarrail.exe': 'Honkai Star Rail',
    'starrail.exe': 'Honkai Star Rail',
    'zenlesszonezero.exe': 'Zenless Zone Zero',
    'valorant.exe': 'Valorant',
    'valorant-win64-shipping.exe': 'Valorant',
    'riotclientux.exe': 'Riot Client',
    'riot client.exe': 'Riot Client',
    'steam.exe': 'Steam',
    'league of legends.exe': 'League of Legends',
    'leagueclient.exe': 'League of Legends',
    'overwatch.exe': 'Overwatch',
    'cs2.exe': 'Counter-Strike 2',
    'dota2.exe': 'Dota 2',
    'minecraft.exe': 'Minecraft',
    'javaw.exe': 'Minecraft',
}

# Processes that host the Snipping Tool or Windows Shell flyouts
SNIP_HOST_PROCESSES = {
    'screenclippinghost.exe',
    'snippingtool.exe',
    'shellexperiencehost.exe',
    'searchhost.exe',
    'startmenuexperiencehost.exe',
    'textinputhost.exe',
    'taskmgr.exe',
    'lockapp.exe',
}

# Overlays and HUDs that should never be identified as the main application
OVERLAY_PROCESSES = {
    'gameoverlayui.exe',
    'gamebar.exe',
    'gamebarft.exe',
    'nvidia share.exe',
    'rtss.exe',
    'rtsshooks.exe',
    'overwolf.exe',
    'screensplitterhook64app.exe',
    'discordhook.exe',
    'discordhookhelper.exe',
    'discordhookhelper64.exe',
    'discord-overlay.exe',
    'discordoverlay.exe',
}

KNOWN_OVERLAY_TITLES = {
    'discord overlay',
    'discord overlay input trap',
    'discord overlay host',
    'discord voice overlay',
    'discord game overlay',
    'geforce in-game overlay',
    'nvidia geforce overlay',
    'steam overlay',
    'xbox game bar',
    'game bar',
    'rtss',
}

# Processes to ignore when searching for target windows
IGNORE_PROCESSES = SNIP_HOST_PROCESSES | OVERLAY_PROCESSES

# Tolerances
DRAG_MATCH_TOLERANCE_PX = 8   # Allow small pixel difference due to DPI scaling or cursor border
DRAG_MAX_AGE_SEC = 10.0       # Max age of mouse drag to correlate with newly saved screenshot
FILE_READY_TIMEOUT_SEC = 8.0  # Max time to wait for file writing to finish

from snipping_settings import (
    describe_watch_sources,
    get_custom_output_dir,
    get_settings_path,
    resolve_watch_folders,
    set_custom_output_dir,
)

# Optional static override for organized subfolders (prefer persistent settings via snipping_settings)
ORGANIZED_DESTINATION_DIR = None


def resolve_screenshots_folders(create_if_missing: bool = True):
    """
    Dynamically detect the user's active Screenshots folders from Snipping Tool settings
    and Windows Known Folders / Explorer User Shell Folders.
    """
    return resolve_watch_folders(create_if_missing=create_if_missing)
