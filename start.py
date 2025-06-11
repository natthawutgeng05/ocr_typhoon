import os
import sys
import subprocess

def main():
    # Get port from environment variable, default to 8080
    port = os.environ.get('PORT', '8080')
    
    print(f"Starting application on port {port}")
    
    # Build gunicorn command
    cmd = [
        'gunicorn',
        '--bind', f'0.0.0.0:{port}',
        'app:app',
        '--timeout', '300',
        '--workers', '1',
        '--log-level', 'info',
        '--access-logfile', '-',
        '--error-logfile', '-'
    ]
    
    # Execute gunicorn
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error starting gunicorn: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()