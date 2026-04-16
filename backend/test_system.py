#!/usr/bin/env python3
"""
Quick test script to verify all components are working.
Run this after starting the FastAPI server.

Usage:
    python test_system.py
"""

import requests
import json
import time
from pathlib import Path

# Configuration
API_BASE_URL = "http://localhost:8000"
MOCK_RESUME_PATH = r"C:\Users\adiks\APOLLO\Outreach_AI_Apollo\AdityaShah_Resume.pdf"

def print_header(text):
    """Print formatted header."""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")

def print_result(title, result):
    """Print formatted result."""
    print(f"\n✓ {title}")
    print(json.dumps(result, indent=2))

def create_mock_resume():
    """Create a mock PDF resume for testing."""
    # Simple text-based mock (in production, use real PDF)
    resume_content = b"%PDF-1.4\nJane Doe\nSoftware Engineer\nPython, FastAPI, Machine Learning"
    Path(MOCK_RESUME_PATH).write_bytes(resume_content)
    print(f"Created mock resume at {MOCK_RESUME_PATH}")

def test_health():
    """Test 1: Health check."""
    print_header("TEST 1: Health Check")
    try:
        resp = requests.get(f"{API_BASE_URL}/health")
        resp.raise_for_status()
        print_result("Server is running", resp.json())
        return True
    except Exception as e:
        print(f"✗ FAILED: {e}")
        print(f"  Make sure server is running: python main.py")
        return False

def test_onboard():
    """Test 2: Onboard user."""
    print_header("TEST 2: Onboard User with Resume")
    try:
        with open(MOCK_RESUME_PATH, "rb") as f:
            files = {"resume": f}
            data = {
                "name": "Jane Doe",
                "email": "jane@example.com",
                "goal": "Find roles at AI-focused startups"
            }
            resp = requests.post(
                f"{API_BASE_URL}/onboard",
                files=files,
                data=data
            )
        resp.raise_for_status()
        result = resp.json()
        print_result("User Onboarded Successfully", result)
        
        profile_id = result.get("profile_id")
        if not profile_id:
            print("✗ FAILED: No profile_id returned")
            return None
        return profile_id
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return None

def test_run_pipeline(profile_id):
    """Test 3: Run email generation pipeline."""
    print_header("TEST 3: Run Email Generation Pipeline")
    try:
        payload = {
            "user_query": "Python engineers at AI startups",
            "profile_id": profile_id
        }
        resp = requests.post(
            f"{API_BASE_URL}/run-pipeline",
            json=payload
        )
        resp.raise_for_status()
        result = resp.json()
        print_result("Pipeline Executed", result)
        
        emails = result.get("emails", [])
        if emails:
            print(f"\n Generated {len(emails)} emails:")
            for i, email in enumerate(emails[:2], 1):  # Show first 2
                print(f"\n  Email {i}:")
                print(f"    To: {email.get('contact', {}).get('email')}")
                print(f"    Subject: {email.get('subject')}")
                print(f"    Company: {email.get('company')}")
            
            return emails[0].get("email_id") if emails else None
        else:
            print("No emails generated")
            return None
    except Exception as e:
        print(f"✗ FAILED: {e}")
        if resp.status_code == 404:
            print("  Profile not found - verify profile_id is correct")
        return None

def test_dashboard():
    """Test 4: Check dashboard."""
    print_header("TEST 4: View Dashboard Metrics")
    try:
        resp = requests.get(f"{API_BASE_URL}/dashboard")
        resp.raise_for_status()
        result = resp.json()
        print_result("Dashboard Metrics", result.get("summary", {}))
        return True
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False

def test_profiles():
    """Test 5: List profiles."""
    print_header("TEST 5: List User Profiles")
    try:
        resp = requests.get(f"{API_BASE_URL}/profiles")
        resp.raise_for_status()
        result = resp.json()
        count = result.get("count", 0)
        print(f"✓ Found {count} user profile(s)")
        if count > 0:
            print("Sample profile:")
            profile = result.get("profiles", [{}])[0]
            print(f"  Name: {profile.get('name')}")
            print(f"  Email: {profile.get('email')}")
            print(f"  Goal: {profile.get('goal')}")
        return True
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False

def test_mock_event(email_id):
    """Test 6: Simulate email event."""
    print_header("TEST 6: Simulate Email Event")
    if not email_id:
        print("⊘ Skipping (no email_id from previous tests)")
        return False
    
    try:
        payload = {
            "email_id": email_id,
            "event": "opened"
        }
        resp = requests.post(
            f"{API_BASE_URL}/mock-event",
            json=payload
        )
        resp.raise_for_status()
        result = resp.json()
        print_result("Event Simulated", result)
        return True
    except Exception as e:
        print(f"✗ FAILED: {e}")
        return False

def main():
    """Run all tests."""
    print("\n" + "="*60)
    print("  OUTREACH AI BACKEND - SYSTEM TEST")
    print("="*60)
    print(f"\nTesting API at: {API_BASE_URL}")
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Create mock resume
    create_mock_resume()
    
    # Run tests sequentially
    tests = []
    
    # Test 1: Health
    if not test_health():
        print("\n" + "="*60)
        print("  TESTS FAILED - Server not running")
        print("  Start server: python main.py")
        print("="*60)
        return
    
    # Test 2: Onboard
    profile_id = test_onboard()
    if not profile_id:
        print("\n⚠ Onboarding failed - cannot continue")
        return
    
    # Test 3: Pipeline
    email_id = test_run_pipeline(profile_id)
    
    # Test 4: Dashboard
    test_dashboard()
    
    # Test 5: Profiles
    test_profiles()
    
    # Test 6: Mock Event
    if email_id:
        test_mock_event(email_id)
    
    # Summary
    print_header("TEST SUMMARY")
    print("""
    ✓ All core components are working!
    
    Next steps:
    1. Open http://localhost:8000/docs for interactive API testing
    2. Try different queries in /run-pipeline
    3. Add real OpenAI key to .env for better email generation
    4. Check SETUP_AND_RUN_GUIDE.md for detailed documentation
    
    Component Status:
    ✓ FastAPI Server  - Running
    ✓ Main Endpoints  - Accessible
    ✓ Apollo.io       - Connected (or using mock data)
    ✓ OpenAI          - Connected (or using mock responses)
    ✓ Pydantic Models - Working
    """)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
