#!/bin/bash

sudo apt-get update
sudo apt-get install ca-certificates curl gnupg -qy
sudo curl -fsSL http://build.openmodelica.org/apt/openmodelica.asc | \
  sudo gpg --dearmor -o /usr/share/keyrings/openmodelica-keyring.gpg

echo "deb [arch=amd64 signed-by=/usr/share/keyrings/openmodelica-keyring.gpg] \
  https://build.openmodelica.org/apt \
  noble \
  stable" | sudo tee /etc/apt/sources.list.d/openmodelica.list

sudo apt update
sudo apt install --no-install-recommends omc -qy
