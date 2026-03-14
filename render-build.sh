#!/usr/bin/env bash
# exit on error
set -o errexit

STORAGE_DIR=/opt/render/project/.render

if [[ ! -d $STORAGE_DIR/chrome ]]; then
  echo "...Downloading Chrome for Testing"
  mkdir -p $STORAGE_DIR/chrome
  cd $STORAGE_DIR/chrome
  
  wget -q -O chrome-linux64.zip https://storage.googleapis.com/chrome-for-testing-public/122.0.6261.128/linux64/chrome-linux64.zip
  unzip -q -o chrome-linux64.zip
  rm chrome-linux64.zip
  
  wget -q -O chromedriver-linux64.zip https://storage.googleapis.com/chrome-for-testing-public/122.0.6261.128/linux64/chromedriver-linux64.zip
  unzip -q -o chromedriver-linux64.zip
  rm chromedriver-linux64.zip
else
  echo "...Using Chrome from cache"
fi

# Return to script root
cd /opt/render/project/src

echo "==> Upgrading pip..."
python -m pip install --upgrade pip

echo "==> Installing requirements..."
pip install -r requirements.txt

echo "==> Build complete!"
