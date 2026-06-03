import socket
import uvicorn
import os
import sys

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Doesn't even need to be reachable
        s.connect(('8.8.8.8', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

if __name__ == "__main__":
    local_ip = get_local_ip()
    
    print("=" * 60)
    print("      TiBe ULTRA AI NEXT-GEN VIDEO SUITE (SaaS)")
    print("=" * 60)
    print(" [OK] Backend API v2.0 Loaded successfully!")
    print(" [OK] JWT Auth & User Management System")
    print(" [OK] Subscription / Unit System (Stripe + PayPal)")
    print(" [OK] 30s Ad Network for Free Tier")
    print(" [OK] Multi-Threaded Ultra Enhancement Engine")
    print(" [OK] Custom Output Directory Support")
    print("-" * 60)
    print("  CONNECT YOUR DEVICES:")
    print(f"  * Local Machine:   http://localhost:8000")
    print(f"  * Mobile/Network:  http://{local_ip}:8000")
    print("-" * 60)
    print("  INSTRUCTIONS:")
    print("  1. Register an account on the web UI")
    print("  2. Buy units or watch a free ad to download")
    print("  3. To share globally, run 'start_public_link.bat'")
    print("=" * 60)
    print("Starting FastAPI Uvicorn engine...\n")
    
    # Run uvicorn programmatically
    try:
        uvicorn.run("backend_api:app", host="0.0.0.0", port=8000, reload=True)
    except KeyboardInterrupt:
        print("\n[!] TiBe Server stopped by user.")
    except Exception as e:
        print(f"\n[!] Error launching server: {e}")
