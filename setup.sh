#!/bin/bash

# Update system
sudo apt-get update

# Install Python, Node.js, and required packages
sudo apt-get install -y python3-full python3-pip python3-venv nodejs npm nginx

# Create directory for the app
mkdir -p /home/ubuntu/openmanus
cd /home/ubuntu/openmanus

# Clone your repository (replace with your repo URL)
git clone https://github.com/HomologyAI/OpenManus.git .
git checkout feature/ui

# Setup Python virtual environment
python3 -m venv venv
source venv/bin/activate

# Setup Backend
pip install -r requirements.txt

# Setup Frontend
cd ui
npm install
npm run build
cd ..

# Fix permissions for the entire path
sudo chmod 755 /home
sudo chmod 755 /home/ubuntu
sudo chmod 755 /home/ubuntu/openmanus
sudo chmod 755 /home/ubuntu/openmanus/ui
sudo chmod 755 /home/ubuntu/openmanus/ui/build

# Set proper ownership and permissions for build directory
sudo chown -R www-data:www-data /home/ubuntu/openmanus/ui/build
sudo find /home/ubuntu/openmanus/ui/build -type d -exec chmod 755 {} \;
sudo find /home/ubuntu/openmanus/ui/build -type f -exec chmod 644 {} \;

# Add www-data to ubuntu group for shared access
sudo usermod -a -G ubuntu www-data

# Configure nginx
sudo tee /etc/nginx/conf.d/openmanus.conf << EOF
server {
    listen 80;
    server_name _;

    # Enable logging
    access_log /var/log/nginx/openmanus_access.log;
    error_log /var/log/nginx/openmanus_error.log;

    # Serve frontend
    location / {
        root /home/ubuntu/openmanus/ui/build;
        try_files \$uri \$uri/ /index.html =404;
        index index.html;
    }

    # Handle static files
    location /static/ {
        root /home/ubuntu/openmanus/ui/build;
        expires 30d;
        add_header Cache-Control "public, no-transform";
    }

    # Proxy backend requests
    location /api/ {
        proxy_pass http://127.0.0.1:8009/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host \$host;
        proxy_cache_bypass \$http_upgrade;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
    }
}
EOF

# Remove default nginx config
sudo rm -f /etc/nginx/conf.d/default.conf

# Ensure nginx directories have correct permissions
sudo mkdir -p /var/log/nginx
sudo chown -R www-data:www-data /var/log/nginx
sudo chmod -R 755 /var/log/nginx

# Start services
sudo systemctl start nginx
sudo systemctl enable nginx

# Create systemd service for backend
sudo tee /etc/systemd/system/openmanus.service << EOF
[Unit]
Description=OpenManus Backend Service
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/openmanus
Environment="PATH=/home/ubuntu/openmanus/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/home/ubuntu/openmanus/venv/bin/gunicorn --bind 127.0.0.1:8009 --log-level debug flask_app:app
Restart=always
StandardOutput=append:/var/log/openmanus.log
StandardError=append:/var/log/openmanus.error.log

[Install]
WantedBy=multi-user.target
EOF

# Create log files and set permissions for backend service
sudo touch /var/log/openmanus.log /var/log/openmanus.error.log
sudo chown ubuntu:ubuntu /var/log/openmanus.log /var/log/openmanus.error.log
sudo chmod 644 /var/log/openmanus.log /var/log/openmanus.error.log

# Reload systemd and start backend service
sudo systemctl daemon-reload
sudo systemctl start openmanus
sudo systemctl enable openmanus

# Final nginx restart to ensure all changes are applied
sudo systemctl restart nginx

# Show service statuses
echo "Checking nginx status:"
sudo systemctl status nginx
echo "Checking openmanus status:"
sudo systemctl status openmanus
