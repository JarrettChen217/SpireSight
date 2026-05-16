:: packaging/build.bat
@echo off
pushd "%~dp0\.."
pip install pyinstaller
pyinstaller --noconfirm packaging\spiresight.spec
echo Bundle: dist\SpireSight\
popd
