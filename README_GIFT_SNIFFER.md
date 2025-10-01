# TikTok Gift Sniffer GUI

A standalone GUI tool for monitoring TikTok live stream gifts without affecting main application configurations.

## Features

- **Independent Configuration**: Uses `gift_sniffer.json` for settings (doesn't touch `gift_map.json`)
- **API Key Management**: Input and persist EulerStream API key
- **Multi-Target Monitoring**: Monitor multiple TikTok users simultaneously
- **Individual Control**: Start/stop monitoring for individual targets or all at once
- **Gift Tracking**: Each target outputs to `gifts_seen_<username>.json`
- **Template Export**: Export all collected gifts to `gift_map_template.json` for easy mapping

## Installation

```bash
pip install PySide6 TikTokLive
```

## Usage

```bash
python gift_sniffer.py
```

## How to Use

1. **Set API Key**: Enter your EulerStream API key (from eulerstream.com) in the top section
2. **Add Targets**: Enter a TikTok username or full URL in the "新增目標" section
   - Format: `@username`, `username`, or `https://www.tiktok.com/@username`
   - Click "加入" to add to the monitoring list
3. **Start Monitoring**: 
   - Select specific targets and click "開始（選取）"
   - Or click "全部開始" to monitor all targets
4. **View Progress**: The table shows status, total gifts seen, and last update time for each target
5. **Stop Monitoring**: Use "停止（選取）" or "全部停止" to stop monitoring
6. **Remove Targets**: Select targets and click "刪除選取" to remove from list
7. **Export Template**: Click "匯出映射模板" to export all seen gifts to a JSON template file

## Output Files

- `gift_sniffer.json`: Configuration file (API key, window geometry, target list)
- `gifts_seen_<username>.json`: Gift data for each monitored user
- `gift_map_template.json`: Exported template with all collected gifts (gid, kw, path)

## Gift Data Format

Each `gifts_seen_<username>.json` file contains:

```json
{
  "5655": {
    "gift_id": "5655",
    "gift_name": "Rose",
    "count_total": 10,
    "first_seen_at": "2025-01-01 12:00:00",
    "last_seen_at": "2025-01-01 12:30:00"
  }
}
```

## Template Export Format

The exported `gift_map_template.json` contains:

```json
[
  {
    "gid": "5655",
    "kw": "Rose",
    "path": ""
  }
]
```

Fill in the `path` field with your media file paths as needed.

## Testing

Run the standalone tests to verify core functionality:

```bash
python test_gift_sniffer_standalone.py
```

## Requirements

- Python 3.7+
- PySide6 (for GUI)
- TikTokLive (version 6.6.1+ recommended)
- EulerStream API key (for TikTok connection)

## Notes

- This tool operates independently from the main application
- Window position and size are automatically saved and restored
- API key is stored locally in `gift_sniffer.json`
- Each target can be monitored independently
- All monitoring can run simultaneously for multiple targets
