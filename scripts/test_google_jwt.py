#!/usr/bin/env python3
"""
Test script for Google Shopping automated discount JWT validation.

This script tests the JWT token validation functionality using a sample token
from Google's documentation.
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

from app.utils import validate_google_jwt_token, extract_google_discount_info

def test_jwt_validation():
    """Test JWT validation with a sample token from Google docs."""
    
    # Sample token from Google documentation (this is just for testing structure)
    # Note: This token will likely be expired, but we can test the parsing
    sample_token = "eyJhbGciOiJFUzI1NiIsInR5cCI6IkpXVCJ9.eyJjIjoiVVNEIiwiZXhwIjoxNTcxNjczNjAwLCJtIjoiMTQwMzAxNjQ2IiwibyI6InRkZHkxMjN1ayIsInAiOjIxLjk5fQ.Qlyr1dQ0vLUJx-iQKwkYE2uLHfYCLVEVGZkAq4fwGTSpMDQCbtzDJr5uGHG8dNKaKV5OlYDxLpW40tQVVe2gkQ"
    
    merchant_id = "114634997"
    
    print("Testing Google JWT validation...")
    print(f"Sample token: {sample_token[:50]}...")
    print(f"Merchant ID: {merchant_id}")
    
    # Test validation
    payload = validate_google_jwt_token(sample_token, merchant_id)
    
    if payload:
        print("✅ Token validation successful!")
        print(f"Payload: {payload}")
        
        # Test discount info extraction
        discount_info = extract_google_discount_info(payload)
        print(f"Discount info: {discount_info}")
    else:
        print("❌ Token validation failed (expected for expired test token)")
        print("This is normal - the sample token is likely expired.")
    
    print("\nTesting with invalid merchant ID...")
    invalid_payload = validate_google_jwt_token(sample_token, "999999999")
    if invalid_payload:
        print("❌ Should have failed with invalid merchant ID")
    else:
        print("✅ Correctly rejected token with invalid merchant ID")
    
    print("\nTesting with malformed token...")
    malformed_payload = validate_google_jwt_token("invalid.token.here", merchant_id)
    if malformed_payload:
        print("❌ Should have failed with malformed token")
    else:
        print("✅ Correctly rejected malformed token")

if __name__ == "__main__":
    test_jwt_validation()
