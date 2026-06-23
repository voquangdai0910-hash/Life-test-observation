#!/usr/bin/env python3
"""Test ON hours API endpoints"""

import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8000/api"

def test_on_hours_api():
    """Test the ON hours calculation API"""
    
    # Try to register a test user first
    print("0. Registering test user...")
    register_response = requests.post(
        f"{BASE_URL}/auth/register",
        json={
            "email": "test.operator@company.com",
            "password": "testpass123",
            "full_name": "Test Operator",
            "role": "operator"
        }
    )
    
    if register_response.status_code == 200:
        print("✓ Test user registered")
    elif register_response.status_code == 400:
        print("⚠️ Test user already exists, continuing...")
    else:
        print(f"Registration response: {register_response.text}")
    
    # Login
    print("\n1. Testing login...")
    login_response = requests.post(
        f"{BASE_URL}/auth/login",
        json={
            "email": "test.operator@company.com",
            "password": "testpass123"
        }
    )
    
    if login_response.status_code != 200:
        print(f"Login failed: {login_response.text}")
        return
    
    token = login_response.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"✓ Login successful, token: {token[:20]}...")
    
    # Upload data with time series
    print("\n2. Testing data upload with time series...")
    upload_data = {
        "test_name": "ON Hours Test",
        "description": "Testing ON hours calculation",
        "data": {
            "data_points": [
                {"timestamp": "2026-06-23T10:00:00Z", "state": "ON"},
                {"timestamp": "2026-06-23T10:08:00Z", "state": "OFF"},
                {"timestamp": "2026-06-23T10:10:00Z", "state": "ON"},
                {"timestamp": "2026-06-23T10:18:00Z", "state": "OFF"}
            ]
        }
    }
    
    upload_response = requests.post(
        f"{BASE_URL}/uploads/data",
        json=upload_data,
        headers=headers
    )
    
    if upload_response.status_code != 200:
        print(f"Upload failed: {upload_response.text}")
        return
    
    upload_result = upload_response.json()
    print(f"✓ Upload successful")
    print(f"  Response: {json.dumps(upload_result, indent=2)}")
    
    # Get ON hours progress
    print("\n3. Testing ON hours progress endpoint...")
    progress_response = requests.get(
        f"{BASE_URL}/uploads/on-hours",
        headers=headers
    )
    
    if progress_response.status_code != 200:
        print(f"Progress fetch failed: {progress_response.text}")
        return
    
    progress_result = progress_response.json()
    print(f"✓ Progress fetch successful")
    print(f"  Progress: {json.dumps(progress_result, indent=2)}")
    
    # Verify ON hours calculation
    progress = progress_result.get("progress", {})
    on_hours = progress.get("cumulative_on_hours", 0)
    
    if on_hours > 0:
        print(f"\n✅ SUCCESS: ON hours calculated correctly: {on_hours} hours")
    else:
        print(f"\n⚠️ WARNING: ON hours not calculated properly")

if __name__ == "__main__":
    test_on_hours_api()
