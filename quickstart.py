#!/usr/bin/env python
"""
Quick Start Guide for VideoClipper
Run this script to verify everything is set up correctly.
"""

import os
import sys
from pathlib import Path

def check_environment():
    """Check if environment is properly configured."""
    print("🔍 Checking VideoClipper environment...\n")
    
    errors = []
    warnings = []
    
    # Check .env file
    if not Path(".env").exists():
        errors.append("Missing .env file - copy .env.example to .env and add GROQ_API_KEY")
    else:
        try:
            with open(".env") as f:
                content = f.read()
                if "GROQ_API_KEY" not in content or "gsk_" not in content:
                    warnings.append(".env exists but GROQ_API_KEY may not be set correctly")
        except Exception as e:
            warnings.append(f"Could not read .env: {e}")
    
    # Check Python version
    py_version = sys.version_info
    if py_version.major < 3 or (py_version.major == 3 and py_version.minor < 11):
        warnings.append(f"Python {py_version.major}.{py_version.minor} detected, 3.11+ recommended")
    else:
        print(f"✓ Python {py_version.major}.{py_version.minor} OK")
    
    # Check required directories
    required_dirs = ["backend", "frontend", "backend/temp"]
    for dir_name in required_dirs:
        if Path(dir_name).exists():
            print(f"✓ Directory '{dir_name}' exists")
        else:
            errors.append(f"Missing directory: {dir_name}")
    
    # Check key files
    key_files = [
        "README.md",
        "backend/main.py",
        "backend/requirements.txt",
        "frontend/app.py",
        "frontend/requirements.txt",
        "docker-compose.yml",
    ]
    for file_name in key_files:
        if Path(file_name).exists():
            print(f"✓ File '{file_name}' exists")
        else:
            errors.append(f"Missing file: {file_name}")
    
    print("\n" + "="*60)
    
    if errors:
        print("❌ ERRORS FOUND:")
        for error in errors:
            print(f"   - {error}")
        print()
    
    if warnings:
        print("⚠️  WARNINGS:")
        for warning in warnings:
            print(f"   - {warning}")
        print()
    
    if not errors:
        print("✅ ALL CHECKS PASSED!")
        return True
    else:
        print("Please fix the errors above before proceeding.")
        return False

def show_next_steps():
    """Show user the next steps."""
    print("\n" + "="*60)
    print("📋 NEXT STEPS:")
    print("="*60)
    print()
    print("1️⃣  SET UP ENVIRONMENT:")
    print("   cp .env.example .env")
    print("   # Edit .env and add your GROQ_API_KEY from https://console.groq.com")
    print()
    print("2️⃣  RUN WITH DOCKER COMPOSE (Recommended):")
    print("   docker-compose up")
    print("   # Then open http://localhost:8501 in your browser")
    print()
    print("3️⃣  OR RUN LOCALLY:")
    print("   # Terminal 1 - Backend:")
    print("   cd backend")
    print("   pip install -r requirements.txt")
    print("   python main.py")
    print()
    print("   # Terminal 2 - Frontend:")
    print("   cd frontend")
    print("   pip install -r requirements.txt")
    print("   streamlit run app.py")
    print()
    print("4️⃣  VERIFY INSTALLATION:")
    print("   cd backend")
    print("   python test_components.py")
    print()
    print("📖 For full documentation, see: README.md")
    print("🔧 For detailed fixes, see: FIXES_SUMMARY.md")
    print()

if __name__ == "__main__":
    os.chdir(Path(__file__).parent.absolute())
    
    if check_environment():
        show_next_steps()
        sys.exit(0)
    else:
        sys.exit(1)
