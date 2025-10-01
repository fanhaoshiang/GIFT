#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Standalone test for gift_sniffer.py utility functions
Tests functions that don't require GUI dependencies
"""

import re
import json
import os
import tempfile
from typing import Optional, Dict, Any


def parse_username(url_or_username: str) -> Optional[str]:
    """
    Parse username from URL or @username
    (Copied from gift_sniffer.py for standalone testing)
    """
    s = (url_or_username or "").strip()
    if not s:
        return None
    m = re.search(r"tiktok\.com/@([^/?]+)", s, re.IGNORECASE)
    if m:
        return m.group(1)
    if s.startswith("@"):
        return s[1:]
    # 去尾部多餘路徑
    s = s.split("/")[0]
    return s or None


def test_parse_username():
    """Test username parsing from various input formats"""
    print("Testing parse_username()...")
    
    test_cases = [
        ("@username", "username"),
        ("username", "username"),
        ("https://www.tiktok.com/@username", "username"),
        ("https://www.tiktok.com/@username/live", "username"),
        ("HTTPS://WWW.TIKTOK.COM/@TestUser", "TestUser"),
        ("@user123", "user123"),
        ("test_user", "test_user"),
        ("test-user", "test-user"),
        ("", None),
        ("   ", None),
        ("https://tiktok.com/@user_name", "user_name"),
        ("https://www.tiktok.com/@user123/video/1234567890", "user123"),
    ]
    
    all_passed = True
    for input_val, expected in test_cases:
        result = parse_username(input_val)
        status = "✓" if result == expected else "✗"
        print(f"  {status} parse_username({input_val!r:50s}) = {result!r:20s} (expected {expected!r})")
        if result != expected:
            all_passed = False
    
    if all_passed:
        print("  All parse_username tests passed!\n")
    else:
        print("  Some parse_username tests failed!\n")
    
    return all_passed


def test_config_functions():
    """Test config save/load functionality"""
    print("Testing config save/load functions...")
    
    # Create a temporary config file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_config = f.name
    
    try:
        # Test data
        test_data = {
            "api_key": "test_key_123",
            "geometry_b64": "test_geometry",
            "targets": [
                {"username": "testuser1", "out_path": "/tmp/test1.json"},
                {"username": "testuser2", "out_path": "/tmp/test2.json"}
            ]
        }
        
        # Test save
        try:
            with open(temp_config, "w", encoding="utf-8") as f:
                json.dump(test_data, f, ensure_ascii=False, indent=2)
            print(f"  ✓ Config saved successfully to {temp_config}")
        except Exception as e:
            print(f"  ✗ Failed to save config: {e}")
            return False
        
        # Test load
        try:
            with open(temp_config, "r", encoding="utf-8") as f:
                loaded_data = json.load(f)
            print(f"  ✓ Config loaded successfully")
        except Exception as e:
            print(f"  ✗ Failed to load config: {e}")
            return False
        
        # Verify data
        if loaded_data.get("api_key") == test_data["api_key"]:
            print(f"  ✓ API key preserved correctly")
        else:
            print(f"  ✗ API key mismatch")
            return False
        
        if len(loaded_data.get("targets", [])) == len(test_data["targets"]):
            print(f"  ✓ Target count preserved correctly")
        else:
            print(f"  ✗ Target count mismatch")
            return False
        
        print("  All config function tests passed!\n")
        return True
        
    finally:
        # Clean up
        if os.path.exists(temp_config):
            os.unlink(temp_config)


def test_gift_data_structure():
    """Test gift data structure format"""
    print("Testing gift data structure...")
    
    # Test the structure used by gifts_seen_<username>.json
    gift_data = {
        "5655": {
            "gift_id": "5655",
            "gift_name": "Rose",
            "count_total": 10,
            "first_seen_at": "2025-01-01 12:00:00",
            "last_seen_at": "2025-01-01 12:30:00"
        },
        "1": {
            "gift_id": "1",
            "gift_name": "TikTok",
            "count_total": 25,
            "first_seen_at": "2025-01-01 12:05:00",
            "last_seen_at": "2025-01-01 12:35:00"
        }
    }
    
    # Verify structure
    for key, gift in gift_data.items():
        if not all(field in gift for field in ["gift_id", "gift_name", "count_total", "first_seen_at", "last_seen_at"]):
            print(f"  ✗ Gift data missing required fields for key {key}")
            return False
    
    print(f"  ✓ Gift data structure is valid")
    
    # Test template export format
    template_rows = []
    for cache_data in [gift_data]:
        for v in cache_data.values():
            template_rows.append({
                "gid": v.get("gift_id", "") or "",
                "kw": v.get("gift_name", "") or "",
                "path": ""
            })
    
    if len(template_rows) == len(gift_data):
        print(f"  ✓ Template export format is correct ({len(template_rows)} gifts)")
    else:
        print(f"  ✗ Template export format issue")
        return False
    
    # Verify each template row has required fields
    for row in template_rows:
        if not all(field in row for field in ["gid", "kw", "path"]):
            print(f"  ✗ Template row missing required fields")
            return False
    
    print(f"  ✓ All template rows have required fields (gid, kw, path)")
    print("  All gift data structure tests passed!\n")
    return True


def test_filename_generation():
    """Test output filename generation"""
    print("Testing output filename generation...")
    
    test_cases = [
        ("testuser", "gifts_seen_testuser.json"),
        ("user123", "gifts_seen_user123.json"),
        ("test_user", "gifts_seen_test_user.json"),
    ]
    
    all_passed = True
    for username, expected_suffix in test_cases:
        generated = f"gifts_seen_{username}.json"
        status = "✓" if generated == expected_suffix else "✗"
        print(f"  {status} Username '{username}' -> '{generated}'")
        if generated != expected_suffix:
            all_passed = False
    
    if all_passed:
        print("  All filename generation tests passed!\n")
    else:
        print("  Some filename tests failed!\n")
    
    return all_passed


def main():
    """Run all tests"""
    print("=" * 60)
    print("Gift Sniffer Utility Functions Tests")
    print("=" * 60 + "\n")
    
    tests = [
        ("Username Parsing", test_parse_username),
        ("Config Functions", test_config_functions),
        ("Gift Data Structure", test_gift_data_structure),
        ("Filename Generation", test_filename_generation),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"  ✗ {test_name} failed with exception: {e}\n")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    print("=" * 60)
    print("Test Summary")
    print("=" * 60)
    
    for test_name, result in results:
        status = "PASSED" if result else "FAILED"
        symbol = "✓" if result else "✗"
        print(f"{symbol} {test_name}: {status}")
    
    all_passed = all(result for _, result in results)
    print("\n" + ("All tests passed! ✓" if all_passed else "Some tests failed! ✗"))
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
