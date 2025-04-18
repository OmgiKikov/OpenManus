#!/bin/bash

echo "Starting deployment..."

# Navigate to the application directory
cd /home/ubuntu/openmanus

# Fetch and pull latest changes
echo "Pulling latest code..."
git fetch
git pull

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Install/update backend dependencies
echo "Updating backend dependencies..."
pip install -r requirements.txt

# Update frontend
echo "Updating frontend..."
cd ui

# Reset ownership of build directory to ubuntu user before build
if [ -d "build" ]; then
    echo "Resetting build directory ownership..."
    sudo chown -R ubuntu:ubuntu build
fi

# Clean install and build
echo "Installing npm dependencies..."
npm install

echo "Building frontend..."
npm run build
cd ..

# Fix permissions after build
echo "Fixing permissions..."
sudo chmod 755 /home/ubuntu/openmanus/ui/build
sudo chown -R www-data:www-data /home/ubuntu/openmanus/ui/build
sudo find /home/ubuntu/openmanus/ui/build -type d -exec chmod 755 {} \;
sudo find /home/ubuntu/openmanus/ui/build -type f -exec chmod 644 {} \;

# Restart services
echo "Restarting services..."
sudo systemctl restart openmanus
sudo systemctl restart nginx

# Check services status
echo "Checking services status..."
echo "Nginx status:"
sudo systemctl status nginx
echo "OpenManus status:"
sudo systemctl status openmanus

echo "Deployment completed!"
