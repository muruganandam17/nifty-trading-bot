# 🚀 Deployment Guide - VPS Server Setup

This guide explains how to deploy the trading system to your VPS server.

---

## 📋 Prerequisites

- A VPS server (Ubuntu 20.04+ recommended)
- SSH access to the server
- Domain name (optional, for accessing via URL)

---

## 🔐 Step 1: Get Server Access

You'll need to provide:
- **Server IP Address**: e.g., `192.168.1.100`
- **SSH Username**: usually `root` or a user with sudo
- **SSH Password** or **SSH Key**

---

## 🔧 Step 2: Connect to Server

### Option A: Password Login
```bash
ssh username@your-server-ip
```

### Option B: SSH Key
```bash
ssh -i ~/.ssh/your-key.pem username@your-server-ip
```

---

## 📦 Step 3: Server Setup (I will do this for you)

Once connected, I'll run these commands:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Python and required packages
sudo apt install -y python3 python3-pip python3-venv git

# Create trading system directory
mkdir -p ~/trading_system
cd ~/trading_system

# Clone or upload your code
# (I'll copy the code from local)

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Create systemd service for auto-start
sudo nano /etc/systemd/system/trading.service
```

---

## ⚙️ Step 4: Systemd Service Configuration

I'll create a systemd service file:

```ini
[Unit]
Description=Trading System
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/trading_system
Environment="PATH=/home/ubuntu/trading_system/venv/bin"
ExecStart=/home/ubuntu/trading_system/venv/bin/python main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Then enable it:
```bash
sudo systemctl daemon-reload
sudo systemctl enable trading
sudo systemctl start trading
```

---

## 🔒 Step 5: Configure Firewall

```bash
# Allow SSH
sudo ufw allow 22/tcp

# Allow custom port if needed
# sudo ufw allow 8000/tcp

# Enable firewall
sudo ufw enable
```

---

## 📊 Step 6: Monitoring

View logs:
```bash
# Real-time logs
sudo journalctl -u trading -f

# Past logs
sudo journalctl -u trading --since "1 hour ago"
```

Check status:
```bash
sudo systemctl status trading
```

---

## 🔄 Step 7: Updating the System

To update the trading system:

```bash
# Stop the service
sudo systemctl stop trading

# Pull latest code or upload new files
# (You'll provide updated code)

# Restart
sudo systemctl start trading
```

---

## 📝 Required Information From You

To proceed with deployment, please provide:

| Item | Example |
|------|---------|
| Server IP | 192.168.x.x |
| SSH Username | ubuntu / root |
| SSH Password | ******** |
| SSH Key Path | ~/.ssh/id_rsa (if using key) |
| Server OS | Ubuntu 22.04 |

---

## 🎯 What's Next?

1. **Test locally first** - Make sure the system works on your machine
2. **Provide server details** - Share the credentials above
3. **I'll deploy** - Connect to your server and set everything up
4. **Monitor & test** - Verify it's running correctly

---

## ⚠️ Important Notes

- **Market Hours**: The system will only run during 9:15 - 15:30 IST
- **Auto-restart**: If the system crashes, it will automatically restart
- **Logging**: All trades and errors will be logged
- **Broker**: Currently configured in "demo" mode (no real trades)

---

## ❓ Questions?

Feel free to ask if you need help with:
- Broker integration (Zerodha, Angel One, etc.)
- Adding more symbols
- Modifying the strategy
- Setting up Telegram notifications