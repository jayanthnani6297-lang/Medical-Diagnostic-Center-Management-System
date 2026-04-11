# start_tunnel.py
import subprocess
import sys
import os

print("="*60)
print("🌐 MEDICAL LAB SECURE TUNNEL SETUP")
print("="*60)
print("\nChoose your tunnel option:")

print("\nOPTION 1: serveo.net (Easiest - no install)")
print("   Works from anywhere, free, no signup")
print("   URL: https://medlab.serveo.net")

print("\nOPTION 2: localhost.run (Alternative)")
print("   URL: https://medlab.localhost.run")

print("\nOPTION 3: ngrok (If you have it installed)")
print("   URL: https://xxxx.ngrok.io")

choice = input("\nEnter choice (1, 2, or 3): ")

if choice == '1':
    print("\n🚀 Starting serveo tunnel...")
    print("📱 Your PUBLIC URL will be: https://medlab.serveo.net")
    print("\nPress Ctrl+C to stop the tunnel")
    print("-"*60)
    subprocess.run(["ssh", "-R", "medlab.serveo.net:80:localhost:5000", "serveo.net"])

elif choice == '2':
    print("\n🚀 Starting localhost.run tunnel...")
    print("📱 Your PUBLIC URL will be shown below")
    print("\nPress Ctrl+C to stop the tunnel")
    print("-"*60)
    subprocess.run(["ssh", "-R", "80:localhost:5000", "nokey@localhost.run"])

elif choice == '3':
    print("\n🚀 Starting ngrok tunnel...")
    subprocess.run(["ngrok", "http", "5000"])

else:
    print("Invalid choice")