"""Prepare a development environment: Python dependencies, frontend dependencies and the CSS bundle."""
import subprocess
import sys
import shutil
from pathlib import Path


def run_command(cmd, cwd=None):
    """Run a shell command and return exit code."""
    try:
        result = subprocess.run(cmd, cwd=cwd, check=False)
        return result.returncode
    except FileNotFoundError as e:
        print(f"Error: Command not found: {e}")
        return 1


def check_requirements():
    """Check if required tools are installed."""
    print("\nChecking requirements...")
    
    # Check Python
    print(" Python:", sys.version.split()[0])
    
    # Check pip
    if not shutil.which("pip"):
        print(" pip not found")
        return False

    
    # Check npm
    if not shutil.which("npm"):
        print("  npm/Node.js not found")
        print("    → Install from: https://nodejs.org/")
        return False
    
    return True


def main():
    """Main setup routine."""
    project_root = Path(__file__).resolve().parents[1]
    app_dir = project_root / "app"
    
    print("Cocos Setup")
    print("=" * 50)
    
    # Validate requirements
    if not check_requirements():
        print("\n Setup failed: Missing required tools")
        return 1
    
    # Check if requirements.txt exists
    requirements_file = project_root / "requirements.txt"
    if not requirements_file.exists():
        print(f"\n requirements.txt not found at {requirements_file}")
        return 1
    
    # Check if app directory exists
    if not app_dir.exists():
        print(f"\n app directory not found at {app_dir}")
        return 1
    
    # Install Python dependencies
    print("\nInstalling Python dependencies...")
    if run_command([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], 
                   cwd=project_root):
        print("Failed to install Python dependencies")
        return 1
    
    # Install frontend dependencies
    print("\nInstalling frontend dependencies (Tailwind + daisyUI)...")
    if run_command(["npm", "install"], cwd=app_dir):
        print("Failed to install npm dependencies")
        return 1
    
    # Build CSS
    print("\nBuilding frontend CSS bundle...")
    if run_command(["npm", "run", "build:css"], cwd=app_dir):
        print("Failed to build CSS")
        return 1
    
    print("\n" + "=" * 50)
    print("Setup completed successfully!")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())