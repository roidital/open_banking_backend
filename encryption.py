"""
Encryption utilities for secure credential storage.
Uses AES-256-GCM for authenticated encryption.
"""
import os
import base64
import json
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from config import Config


def get_encryption_key():
    """Get or generate encryption key."""
    key = Config.ENCRYPTION_KEY
    if not key:
        raise ValueError("ENCRYPTION_KEY environment variable must be set in production")
    # Decode from base64 if stored that way
    try:
        return base64.b64decode(key)
    except:
        # If not base64, use as-is (for dev only)
        return key.encode()[:32].ljust(32, b'\0')


def encrypt_credentials(credentials: dict) -> dict:
    """
    Encrypt credentials dictionary using AES-256-GCM.
    
    Args:
        credentials: Dictionary containing bank credentials
        
    Returns:
        Dictionary with 'encrypted_data' and 'nonce' (both base64 encoded)
    """
    key = get_encryption_key()
    aesgcm = AESGCM(key)
    
    # Generate a random 96-bit nonce
    nonce = os.urandom(12)
    
    # Convert credentials to JSON bytes
    plaintext = json.dumps(credentials).encode('utf-8')
    
    # Encrypt
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    
    return {
        'encrypted_data': base64.b64encode(ciphertext).decode('utf-8'),
        'nonce': base64.b64encode(nonce).decode('utf-8')
    }


def decrypt_credentials(encrypted: dict) -> dict:
    """
    Decrypt credentials from encrypted storage.
    
    Args:
        encrypted: Dictionary with 'encrypted_data' and 'nonce'
        
    Returns:
        Original credentials dictionary
    """
    key = get_encryption_key()
    aesgcm = AESGCM(key)
    
    # Decode from base64
    ciphertext = base64.b64decode(encrypted['encrypted_data'])
    nonce = base64.b64decode(encrypted['nonce'])
    
    # Decrypt
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    
    return json.loads(plaintext.decode('utf-8'))


def generate_encryption_key():
    """Generate a new random encryption key (for setup)."""
    key = os.urandom(32)
    return base64.b64encode(key).decode('utf-8')


if __name__ == '__main__':
    # Helper to generate a new key
    print("New encryption key (save this securely):")
    print(generate_encryption_key())

