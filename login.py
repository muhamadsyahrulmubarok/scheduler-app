import redis
import hashlib
from typing import Optional
import os
from dotenv import load_dotenv
import time
load_dotenv()

class UserAuth:
    def __init__(self):
        """Initialize Redis connection"""
        self.redis_client = redis.Redis(host=os.getenv('REDIS_HOST'), port=os.getenv('REDIS_PORT'), password=os.getenv('REDIS_PASS'), db=3, decode_responses=True)
    
    def _hash_password(self, password: str) -> str:
        """Hash password using SHA-256"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def register_user(self, username: str, password: str) -> bool:
        """Register a new user"""
        # Check if user already exists
        if self.redis_client.hexists('users', username):
            return False
        
        # Hash password and store user
        hashed_password = self._hash_password(password)
        self.redis_client.hset('users', username, hashed_password)
        return True
    
    def login(self, username: str, password: str) -> bool:
        """Authenticate user login"""
        stored_password = self.redis_client.hget('users', username)
        
        if stored_password is None:
            return False
            
        return stored_password == self._hash_password(password)
    
    def create_session(self, username: str) -> str:
        """Create a session for logged in user"""
        session_id = hashlib.sha256(f"{username}{hashlib.sha256(str(time.time()).encode()).hexdigest()}".encode()).hexdigest()
        
        # Store session with 24 hour expiry
        self.redis_client.setex(f"session:{session_id}", 24*60*60, username)
        return session_id
    
    def validate_session(self, session_id: str) -> Optional[str]:
        """Validate a session and return username if valid"""
        return self.redis_client.get(f"session:{session_id}")
    
    def logout(self, session_id: str) -> bool:
        """Remove user session"""
        return bool(self.redis_client.delete(f"session:{session_id}"))