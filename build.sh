# !/bin/bash

cd ./rpm/
rm -rf BUILD BUILDROOT RPMS SRPMS breeze-icons-*.tar.* *.buildlog
cd ./../
rsync -av --exclude='.git' --exclude='rpm' ./ ./breeze-icons-5.90.0
tar  -czf ./rpm/breeze-icons-5.90.0.tar.gz breeze-icons-5.90.0
rm -rf ./breeze-icons-5.90.0
cd ./rpm/
dnf builddep breeze-icons.spec
abb build --nodeps --target=noarch-openmandriva-linux
cd ./../

